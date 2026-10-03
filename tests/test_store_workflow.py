import hashlib
import json
import os
import socket
from datetime import timedelta
from types import SimpleNamespace

import pytest
from conftest import EXAMPLES

from bi_analyst.errors import BIError
from bi_analyst.store import RunStore, atomic_bytes, default_root, now_utc
from bi_analyst.workflow import analyze_deterministic, ingest_run, open_engine


@pytest.fixture
def windows_store_os(monkeypatch):
    # Simulate Windows only for the store; pathlib must keep the host OS semantics.
    simulated_os = SimpleNamespace(**vars(os))
    simulated_os.name = "nt"
    monkeypatch.setattr("bi_analyst.store.os", simulated_os)


def test_default_root_prefers_configured_path_without_evaluating_uid(tmp_path, monkeypatch):
    configured = tmp_path / "configured-runtime"
    monkeypatch.setenv("BI_ANALYST_RUNTIME", str(configured))

    def fail_if_called():
        raise AssertionError("os.getuid() must not be evaluated for a configured runtime")

    monkeypatch.setattr("bi_analyst.store.os.getuid", fail_if_called, raising=False)
    assert default_root() == configured


def test_default_root_supports_windows_without_getuid(tmp_path, monkeypatch):
    monkeypatch.delenv("BI_ANALYST_RUNTIME", raising=False)
    monkeypatch.delattr("bi_analyst.store.os.getuid", raising=False)
    monkeypatch.setattr("bi_analyst.store.tempfile.gettempdir", lambda: str(tmp_path))
    assert default_root() == tmp_path / "evidence-bi"


def test_store_reads_utf8_json_independently_of_windows_code_page(tmp_path):
    store = RunStore(tmp_path / "runtime", owner="phiên-local")
    run_id = store.create()
    store.write(run_id, "report.json", {"description": "Một dòng hàng bán"})
    assert store.manifest(run_id)["owner"] == "phiên-local"
    assert store.read(run_id, "report.json")["description"] == "Một dòng hàng bán"


def test_offline_end_to_end_and_source_immutable(
    tmp_path, contract, policy, request_spec, monkeypatch
):
    def forbid_network(*args, **kwargs):
        raise AssertionError("Unexpected outbound connection")

    monkeypatch.setattr(socket.socket, "connect", forbid_network)
    store = RunStore(tmp_path / "runtime")
    source = EXAMPLES / "sales.csv"
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    run_id = ingest_run(source, contract, policy, store)
    assert store.manifest(run_id)["status"] == "READY"
    result = analyze_deterministic(run_id, store, request_spec)
    assert result["results"][0]["data"]["delta"] == "-400"
    assert store.manifest(run_id)["status"] == "COMPLETED"
    store.delete(run_id)
    assert source.exists() and hashlib.sha256(source.read_bytes()).hexdigest() == before


def test_unmapped_requested_dimension_blocks_before_analytics_tools(
    tmp_path, contract, policy, request_spec, monkeypatch
):
    from bi_analyst.runtime import execute_tool as real_execute_tool

    changed = contract.model_copy(deep=True)
    changed.dimensions = {"Region": "Region"}
    store = RunStore(tmp_path / "runtime")
    run_id = ingest_run(EXAMPLES / "sales.csv", changed, policy, store)
    executed = []

    def record_execution(*args, **kwargs):
        executed.append(args[2].tool)
        return real_execute_tool(*args, **kwargs)

    monkeypatch.setattr("bi_analyst.runtime.execute_tool", record_execution)

    with pytest.raises(BIError) as error:
        analyze_deterministic(run_id, store, request_spec)

    assert error.value.code == "UNKNOWN_DIMENSION"
    assert executed == []


def test_run_isolation_links_and_traversal(tmp_path):
    one = RunStore(tmp_path / "runtime", owner="one")
    two = RunStore(tmp_path / "runtime", owner="two")
    run_id = one.create()
    with pytest.raises(BIError) as err:
        two.manifest(run_id)
    assert err.value.code == "ACCESS_DENIED"
    with pytest.raises(BIError):
        one.manifest("../../etc")
    with pytest.raises(BIError):
        one.write(run_id, "../outside.json", {})


def test_run_rejects_artifact_links(tmp_path):
    one = RunStore(tmp_path / "runtime", owner="one")
    run_id = one.create()
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    try:
        (one._path(run_id) / "report.json").symlink_to(outside)
    except OSError as error:
        if getattr(error, "winerror", None) == 1314:
            pytest.skip("Windows symlink creation requires Developer Mode or elevated privilege")
        raise
    with pytest.raises(BIError):
        one.write(run_id, "report.json", {"bad": 1})
    with pytest.raises(BIError):
        one.read(run_id, "report.json")
    with pytest.raises(BIError):
        one.delete(run_id)
    assert outside.read_text() == "{}"


def test_expiry_and_saved_run(tmp_path):
    store = RunStore(tmp_path / "runtime")
    expired = store.create()
    saved = store.create()
    store.update(saved, saved=True)
    for run in [expired, saved]:
        store.update(run, expires_at=(now_utc() - timedelta(hours=1)).isoformat())
    with pytest.raises(BIError) as error:
        store.manifest(expired)
    assert error.value.code == "RUN_EXPIRED"
    assert store.cleanup_expired() == [expired]
    assert store.manifest(saved)["saved"] is True


def test_failed_ingestion_manifest(tmp_path, contract, policy):
    source = tmp_path / "empty.csv"
    source.write_bytes(b"")
    store = RunStore(tmp_path / "runtime")
    run_id = ingest_run(source, contract, policy, store)
    assert store.manifest(run_id)["status"] == "FAILED"
    assert not (store._path(run_id) / "dataset_profile.json").exists()


def test_source_contract_policy_mutation_invalidates_run(tmp_path, contract, policy):
    store = RunStore(tmp_path / "runtime")
    run_id = ingest_run(EXAMPLES / "sales.csv", contract, policy, store)
    changed = store.read(run_id, "data_policy.json")
    changed["revision"] += 1
    store.write(run_id, "data_policy.json", changed)
    with pytest.raises(BIError) as error:
        open_engine(run_id, store)
    assert error.value.code == "STALE_RUN"


def test_atomic_write_failure_preserves_previous(tmp_path, monkeypatch):
    path = tmp_path / "artifact.json"
    path.write_text('{"old":true}')

    def fail(*args):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr("bi_analyst.store.os.replace", fail)
    with pytest.raises(BIError):
        atomic_bytes(path, b'{"new":true}')
    assert json.loads(path.read_text()) == {"old": True}
    assert not list(tmp_path.glob(".partial-*"))


@pytest.mark.parametrize("winerror", [None, 5, 32, 33])
def test_atomic_write_retries_known_windows_replace_transients(
    tmp_path, monkeypatch, winerror, windows_store_os
):
    path = tmp_path / "artifact.json"
    path.write_text('{"old":true}')
    original_replace = __import__("os").replace
    calls = []

    def flaky_replace(source, target):
        calls.append((source, target))
        if len(calls) == 1:
            error = PermissionError("synthetic Windows replace contention")
            if winerror is not None:
                error.winerror = winerror
            raise error
        original_replace(source, target)

    monkeypatch.setattr("bi_analyst.store.os.replace", flaky_replace)
    atomic_bytes(path, b'{"new":true}')

    assert len(calls) == 2
    assert json.loads(path.read_text()) == {"new": True}
    assert not list(tmp_path.glob(".partial-*"))


def test_atomic_write_retries_transient_replace_twice_then_succeeds(
    tmp_path, monkeypatch, windows_store_os
):
    path = tmp_path / "artifact.json"
    path.write_text('{"old":true}')
    original_replace = __import__("os").replace
    calls = []
    waits = []

    monkeypatch.setattr("bi_analyst.store.time.sleep", waits.append)

    def flaky_replace(source, target):
        calls.append((source, target))
        if len(calls) <= 2:
            error = OSError("synthetic Windows sharing violation")
            error.winerror = 32
            raise error
        original_replace(source, target)

    monkeypatch.setattr("bi_analyst.store.os.replace", flaky_replace)
    atomic_bytes(path, b'{"new":true}')

    assert len(calls) == 3
    assert waits == [0.01, 0.05]
    assert json.loads(path.read_text()) == {"new": True}
    assert not list(tmp_path.glob(".partial-*"))


def test_atomic_write_retries_are_bounded_and_safe_after_transient_exhaustion(
    tmp_path, monkeypatch, windows_store_os
):
    path = tmp_path / "artifact.json"
    path.write_text('{"old":true}')
    calls = []

    def always_busy(*args):
        calls.append(args)
        error = PermissionError("synthetic Windows sharing violation")
        error.winerror = 32
        raise error

    monkeypatch.setattr("bi_analyst.store.os.replace", always_busy)
    with pytest.raises(BIError) as error:
        atomic_bytes(path, b'{"new":true}')

    assert error.value.code == "STORAGE_ERROR"
    assert len(calls) == 3
    assert json.loads(path.read_text()) == {"old": True}
    assert not list(tmp_path.glob(".partial-*"))


def test_atomic_write_does_not_retry_arbitrary_windows_oserror(
    tmp_path, monkeypatch, windows_store_os
):
    path = tmp_path / "artifact.json"
    path.write_text('{"old":true}')
    calls = []

    def permanent_failure(*args):
        calls.append(args)
        error = OSError("synthetic permanent disk failure")
        error.winerror = 999
        raise error

    monkeypatch.setattr("bi_analyst.store.os.replace", permanent_failure)
    with pytest.raises(BIError) as error:
        atomic_bytes(path, b'{"new":true}')

    assert error.value.code == "STORAGE_ERROR"
    assert len(calls) == 1
    assert json.loads(path.read_text()) == {"old": True}
    assert not list(tmp_path.glob(".partial-*"))


def test_run_store_manifest_failure_preserves_safe_context(tmp_path, monkeypatch):
    store = RunStore(tmp_path / "runtime", owner="offline-diagnosis")
    run_id = store.create(metadata={"purpose": "fault-injection"})
    before = store.manifest(run_id)

    def fail(*args):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr("bi_analyst.store.os.replace", fail)
    with pytest.raises(BIError) as error:
        store.update(run_id, status="RUNNING", diagnostic_marker="safe-only")

    assert error.value.code == "STORAGE_ERROR"
    assert store.manifest(run_id) == before
    assert "diagnostic_marker" not in store.manifest(run_id)
    assert not list(store._path(run_id).glob(".partial-*"))


def test_startup_cleanup_reaches_abandoned_sessions_but_preserves_saved(tmp_path):
    from bi_analyst.store import cleanup_expired_sessions

    abandoned = RunStore(tmp_path / "runtime", owner="closed-browser-session")
    run_id = abandoned.create()
    abandoned.update(run_id, expires_at=(now_utc() - timedelta(hours=1)).isoformat())
    kept = RunStore(tmp_path / "runtime", owner="saved-session")
    saved_id = kept.create()
    kept.update(saved_id, saved=True, expires_at=(now_utc() - timedelta(hours=1)).isoformat())
    assert cleanup_expired_sessions(tmp_path / "runtime") == 1
    assert not abandoned._path(run_id).exists()
    assert kept.manifest(saved_id)["saved"] is True


def test_operator_policy_file_revocation_invalidates_existing_run(tmp_path, contract, policy):
    source = tmp_path / "operator_policy.json"
    source.write_text(policy.model_dump_json())
    store = RunStore(tmp_path / "runtime")
    run_id = ingest_run(EXAMPLES / "sales.csv", contract, policy, store, policy_path=source)
    policy.revision += 1
    source.write_text(policy.model_dump_json())
    with pytest.raises(BIError) as error:
        open_engine(run_id, store)
    assert error.value.code == "POLICY_CHANGED"


def test_trusted_cli_can_recover_and_delete_saved_ui_session(tmp_path, capsys):
    from bi_analyst.cli import main

    root = tmp_path / "runtime"
    ui = RunStore(root, owner="closed-ui-session")
    run_id = ui.create()
    ui.update(run_id, saved=True)
    assert RunStore(root, owner="different-ui-session").list_runs() == []
    assert main(["--runtime-root", str(root), "runs", "list", "--all-sessions"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["owner"] == "closed-ui-session" and rows[0]["run_id"] == run_id
    assert (
        main(["--runtime-root", str(root), "--owner", rows[0]["owner"], "runs", "delete", run_id])
        == 0
    )
    assert not ui._path(run_id).exists()
