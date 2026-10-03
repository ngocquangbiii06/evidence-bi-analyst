import pytest

from bi_analyst.analysis_store import ValidatedAnalysisStore
from bi_analyst.analytics import Analytics
from bi_analyst.contracts import (
    AnalysisScope,
    TrustedAnalysisLoadContext,
    ValidatedAnalysisArtifact,
    fingerprint,
    required_obligation_ids,
)
from bi_analyst.errors import BIError
from bi_analyst.finding_validation import (
    build_candidate_findings,
    trusted_analysis_context,
    trusted_evidence_call,
    validate_candidate_finding,
)
from bi_analyst.store import RunStore


def _artifact_bundle(dataset, contract, request):
    evidence = Analytics(dataset, contract).compare_periods(request)
    candidate = build_candidate_findings([evidence])[0]
    finding_context = trusted_analysis_context(
        dataset.sha256,
        contract,
        request,
        {
            evidence["evidence_id"]: trusted_evidence_call(
                contract, request, "compare_periods"
            )
        },
    )
    _, validation = validate_candidate_finding(candidate, [evidence], finding_context)
    assert validation.accepted is True

    metric = contract.metric(request.metric_id)
    root_scope = AnalysisScope(
        metric_id=request.metric_id,
        previous=request.previous,
        current=request.current,
        filters=request.filters,
        unit=metric.unit,
        scale=metric.scale,
    )
    required = required_obligation_ids(request, "supported_descriptive")
    fulfilled = ["overall.delta"]
    artifact_body = {
        "schema_version": "1.0",
        "artifact_version": "1.0",
        "validator_version": "1.0",
        "implementation_version": "1.0",
        "dataset_hash": dataset.sha256,
        "confirmed_contract_snapshot": contract.model_dump(mode="json"),
        "contract_fingerprint": fingerprint(contract),
        "root_request": request.model_dump(mode="json"),
        "root_request_fingerprint": fingerprint(request),
        "root_scope": root_scope.model_dump(mode="json"),
        "mode": "deterministic",
        "goal_disposition": "supported_descriptive",
        "trace_revision": 1,
        "investigation_trace": [
            {
                "revision": 1,
                "kind": "tool_call",
                "tool": "compare_periods",
                "evidence_ids": [evidence["evidence_id"]],
                "finding_ids": [candidate.finding_id],
            }
        ],
        "prediction_revisions": [],
        "evidence_registry": {evidence["evidence_id"]: evidence},
        "root_evidence_ids": [evidence["evidence_id"]],
        "findings": [
            {
                "candidate": candidate.model_dump(mode="json"),
                "validation": validation.model_dump(mode="json"),
            }
        ],
        "accepted_finding_ids": [candidate.finding_id],
        "rejected_finding_ids": [],
        "obligations": {
            "required": required,
            "fulfilled": fulfilled,
            "missing": [item for item in required if item not in fulfilled],
            "evidence_by_obligation": {"overall.delta": [evidence["evidence_id"]]},
        },
        "sufficiency_status": "partial",
        "limitations": [],
        "clarification_request": None,
        "execution_status": "succeeded",
        "errors": [],
        "usage": {
            "tool_calls": 1,
            "model_calls": 0,
            "elapsed_seconds": 0.1,
            "input_tokens": None,
            "output_tokens": None,
            "cost_usd": None,
        },
    }
    artifact_body["content_fingerprint"] = fingerprint(artifact_body)
    artifact = ValidatedAnalysisArtifact.model_validate(artifact_body)
    trusted_context = TrustedAnalysisLoadContext(
        dataset_hash=dataset.sha256,
        confirmed_contract_snapshot=contract,
        root_request=request,
        implementation_version="1.0",
        validator_version="1.0",
        finding_context=finding_context,
    )
    return artifact, trusted_context


def _rewrite_fingerprint(payload):
    body = {key: value for key, value in payload.items() if key != "content_fingerprint"}
    payload["content_fingerprint"] = fingerprint(body)
    return payload


def _new_store(tmp_path):
    run_store = RunStore(tmp_path / "runtime")
    return run_store, ValidatedAnalysisStore(run_store), run_store.create()


def test_same_trusted_snapshot_loads_and_revalidates_findings(
    tmp_path, dataset, contract, request_spec
):
    artifact, trusted_context = _artifact_bundle(dataset, contract, request_spec)
    _, store, run_id = _new_store(tmp_path)

    store.write(run_id, artifact)
    loaded = store.load(run_id, trusted_context)

    assert loaded == artifact
    assert loaded.accepted_finding_ids == ["F001"]


def test_missing_artifact_is_explicit_and_never_synthesized(
    tmp_path, dataset, contract, request_spec
):
    _, store, run_id = _new_store(tmp_path)
    _, trusted_context = _artifact_bundle(dataset, contract, request_spec)

    with pytest.raises(BIError) as error:
        store.load(run_id, trusted_context)

    assert error.value.code == "ARTIFACT_MISSING"
    assert "new run" in error.value.message.lower()
    assert not (store.runs._path(run_id) / "validated_analysis.json").exists()


def test_content_tampering_is_rejected_even_when_dependency_context_matches(
    tmp_path, dataset, contract, request_spec
):
    _, store, run_id = _new_store(tmp_path)
    artifact, trusted_context = _artifact_bundle(dataset, contract, request_spec)
    store.write(run_id, artifact)
    path = store.runs._path(run_id) / "validated_analysis.json"
    payload = store.runs.read(run_id, "validated_analysis.json")
    payload["limitations"].append("modified after fingerprint")
    store.runs.write(run_id, "validated_analysis.json", payload)

    with pytest.raises(BIError) as error:
        store.load(run_id, trusted_context)

    assert error.value.code == "TAMPERED_ARTIFACT"
    assert "fingerprint" in error.value.message.lower()
    assert path.exists()


@pytest.mark.parametrize(
    "dependency",
    [
        "dataset_hash",
        "confirmed_contract_snapshot",
        "root_request",
        "implementation_version",
        "validator_version",
    ],
)
def test_changed_artifact_dependency_is_stale_after_content_rehash(
    tmp_path, dataset, contract, request_spec, dependency
):
    _, store, run_id = _new_store(tmp_path)
    artifact, trusted_context = _artifact_bundle(dataset, contract, request_spec)
    store.write(run_id, artifact)
    payload = store.runs.read(run_id, "validated_analysis.json")
    if dependency == "dataset_hash":
        payload[dependency] = "b" * 64
    elif dependency == "confirmed_contract_snapshot":
        payload[dependency]["revision"] += 1
        payload["contract_fingerprint"] = fingerprint(payload[dependency])
    elif dependency == "root_request":
        payload[dependency]["question"] = "A changed approved question"
        payload["root_request_fingerprint"] = fingerprint(payload[dependency])
    else:
        payload[dependency] = "9.9"
    store.runs.write(run_id, "validated_analysis.json", _rewrite_fingerprint(payload))

    with pytest.raises(BIError) as error:
        store.load(run_id, trusted_context)

    assert error.value.code == "STALE_ARTIFACT"
    assert dependency in error.value.message


def test_root_scope_cannot_be_changed_independently_of_its_approved_request(
    tmp_path, dataset, contract, request_spec
):
    _, store, run_id = _new_store(tmp_path)
    artifact, trusted_context = _artifact_bundle(dataset, contract, request_spec)
    store.write(run_id, artifact)
    payload = store.runs.read(run_id, "validated_analysis.json")
    payload["root_scope"]["unit"] = "USD"
    store.runs.write(run_id, "validated_analysis.json", _rewrite_fingerprint(payload))

    with pytest.raises(BIError) as error:
        store.load(run_id, trusted_context)

    assert error.value.code == "INVALID_ARTIFACT"


def test_rehashed_evidence_payload_tampering_is_rejected(tmp_path, dataset, contract, request_spec):
    _, store, run_id = _new_store(tmp_path)
    artifact, trusted_context = _artifact_bundle(dataset, contract, request_spec)
    store.write(run_id, artifact)
    payload = store.runs.read(run_id, "validated_analysis.json")
    evidence_id = next(iter(payload["evidence_registry"]))
    payload["evidence_registry"][evidence_id]["data"]["delta_minor"] += 1
    store.runs.write(run_id, "validated_analysis.json", _rewrite_fingerprint(payload))

    with pytest.raises(BIError) as error:
        store.load(run_id, trusted_context)

    assert error.value.code == "TAMPERED_ARTIFACT"
    assert "evidence" in error.value.message.lower()


def test_old_schema_is_rejected_with_legacy_reason_and_no_upgrade(
    tmp_path, dataset, contract, request_spec
):
    _, store, run_id = _new_store(tmp_path)
    artifact, trusted_context = _artifact_bundle(dataset, contract, request_spec)
    payload = artifact.model_dump(mode="json")
    del payload["artifact_version"]
    store.runs.write(run_id, "validated_analysis.json", _rewrite_fingerprint(payload))

    with pytest.raises(BIError) as error:
        store.load(run_id, trusted_context)

    assert error.value.code == "LEGACY_ARTIFACT"
    assert "new run" in error.value.message.lower()
    assert "artifact_version" not in store.runs.read(run_id, "validated_analysis.json")


def test_atomic_interruption_preserves_previous_validated_artifact(
    tmp_path, dataset, contract, request_spec, monkeypatch
):
    run_store, store, run_id = _new_store(tmp_path)
    artifact, trusted_context = _artifact_bundle(dataset, contract, request_spec)
    store.write(run_id, artifact)
    path = run_store._path(run_id) / "validated_analysis.json"
    before = path.read_bytes()

    changed = artifact.model_dump(mode="json")
    changed["limitations"] = ["different content"]
    replacement = ValidatedAnalysisArtifact.model_validate(_rewrite_fingerprint(changed))

    def fail_replace(*args):
        raise OSError("simulated interruption before replace")

    monkeypatch.setattr("bi_analyst.store.os.replace", fail_replace)
    with pytest.raises(BIError) as error:
        store.write(run_id, replacement)

    assert error.value.code == "STORAGE_ERROR"
    assert path.read_bytes() == before
    assert not list(path.parent.glob(".partial-*"))
    assert store.load(run_id, trusted_context).content_fingerprint == artifact.content_fingerprint


@pytest.mark.parametrize(
    ("mutation", "expected_message"),
    [
        ("missing", "accepted ids"),
        ("extra", "accepted ids"),
        ("rejected_as_accepted", "accepted ids"),
    ],
)
def test_missing_extra_and_rejected_candidate_ids_cannot_be_marked_accepted(
    tmp_path, dataset, contract, request_spec, mutation, expected_message
):
    _, store, run_id = _new_store(tmp_path)
    artifact, trusted_context = _artifact_bundle(dataset, contract, request_spec)
    payload = artifact.model_dump(mode="json")
    if mutation == "missing":
        payload["accepted_finding_ids"] = []
    elif mutation == "extra":
        payload["accepted_finding_ids"].append("F999")
    else:
        payload["findings"][0]["validation"]["interpretation"] = "failed"
        payload["findings"][0]["validation"]["accepted"] = False
        payload["accepted_finding_ids"] = ["F001"]
        payload["rejected_finding_ids"] = []
    store.runs.write(run_id, "validated_analysis.json", _rewrite_fingerprint(payload))

    with pytest.raises(BIError) as error:
        store.load(run_id, trusted_context)
    assert error.value.code == "INVALID_ARTIFACT"
    assert expected_message in error.value.message.lower()


def test_stored_verdict_must_match_fresh_m1_revalidation(
    tmp_path, dataset, contract, request_spec
):
    _, store, run_id = _new_store(tmp_path)
    artifact, trusted_context = _artifact_bundle(dataset, contract, request_spec)
    payload = artifact.model_dump(mode="json")
    payload["findings"][0]["candidate"]["text"] = "A self-certified, altered claim."
    store.runs.write(run_id, "validated_analysis.json", _rewrite_fingerprint(payload))

    with pytest.raises(BIError) as error:
        store.load(run_id, trusted_context)

    assert error.value.code == "FINDING_REVALIDATION_FAILED"
    assert "F001" in error.value.message
    assert "stored" in error.value.message.lower()


def test_rehashed_forged_verdict_is_rejected_by_fresh_m1_validation(
    tmp_path, dataset, contract, request_spec
):
    _, store, run_id = _new_store(tmp_path)
    artifact, trusted_context = _artifact_bundle(dataset, contract, request_spec)
    payload = artifact.model_dump(mode="json")
    payload["findings"][0]["validation"]["numerical"] = "failed"
    payload["findings"][0]["validation"]["accepted"] = False
    payload["accepted_finding_ids"] = []
    payload["rejected_finding_ids"] = ["F001"]
    store.runs.write(run_id, "validated_analysis.json", _rewrite_fingerprint(payload))

    with pytest.raises(BIError) as error:
        store.load(run_id, trusted_context)

    assert error.value.code == "FINDING_REVALIDATION_FAILED"
    assert "F001" in error.value.message


def test_trusted_context_dependencies_must_be_internally_consistent(
    dataset, contract, request_spec
):
    _, trusted_context = _artifact_bundle(dataset, contract, request_spec)
    altered_evidence_context = trusted_context.finding_context.model_copy(
        update={"dataset_hash": "c" * 64}
    )

    with pytest.raises(ValueError):
        TrustedAnalysisLoadContext.model_validate(
            trusted_context.model_dump(mode="python")
            | {"finding_context": altered_evidence_context}
        )


def test_artifact_load_policy_remains_explicit():
    from bi_analyst.contracts import ARTIFACT_LOAD_POLICY

    assert ARTIFACT_LOAD_POLICY == {
        "legacy": "reject_require_new_run",
        "stale": "reject_require_new_run",
        "missing": "report_missing_without_synthesis",
    }
