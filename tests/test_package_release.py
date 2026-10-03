"""Regression tests for the exact, public-safe release selector."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

import scripts.package_release as package_release


def test_is_included_rejects_known_private_paths():
    rejected = (
        ".venv/bin/python",
        ".git/config",
        "src/__pycache__/bi.cpython-312.pyc",
        ".env",
        "runtime/run_store/run.json",
        "examples/evaluation/live_config.m5_r6.json",
        "deliverables/PowerBI_Demo_Current/EvidenceBI.pbip",
        "deliverables/PowerBI_Demo_Refresh_R1/EvidenceBI.pbip",
        "deliverables/verification/t15-candidate-verification.json",
        "docs/BUILD_PROGRESS.md",
        "C:/secrets/key.txt",
        "../outside.txt",
    )
    for path in rejected:
        assert not package_release.is_included(path), path


def test_is_included_allows_public_source_and_r2_artifact():
    for path in (
        "src/bi_analyst/bi.py",
        "tests/test_powerbi.py",
        "docs/FLAGSHIP_EXECUTION_PLAN.md",
        "deliverables/PowerBI_Demo_Refresh_R2/EvidenceBI.pbip",
        "deliverables/verification/dashboard_refresh_r2/engine.json",
    ):
        assert package_release.is_included(path), path


def _fixture_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "examples").mkdir()
    (tmp_path / "examples" / "live_config.example.json").write_text(
        '{"live_enabled": false}\n', encoding="utf-8"
    )
    (tmp_path / ".env").write_text("fake-secret-marker\n", encoding="utf-8")
    (tmp_path / "runtime" / "run_store").mkdir(parents=True)
    (tmp_path / "runtime" / "run_store" / "secret.json").write_text("x", encoding="utf-8")
    extra = tmp_path / "extras.json"
    extra.write_text(
        json.dumps({"files": ["examples/live_config.example.json"]}), encoding="utf-8"
    )
    monkeypatch.setattr(package_release, "PUBLIC_EXTRA_MANIFEST", extra)
    monkeypatch.setattr(package_release, "_tracked_paths", lambda _root: ["src/main.py"])
    return tmp_path


def test_collect_uses_tracked_plus_exact_extras_and_excludes_runtime(tmp_path, monkeypatch):
    root = _fixture_root(tmp_path, monkeypatch)
    records = package_release.collect_release_files(root)
    paths = {str(item["path"]) for item in records}
    assert paths == {"src/main.py", "examples/live_config.example.json"}


def test_manifest_and_zip_use_exact_bytes_and_reject_drift(tmp_path, monkeypatch):
    root = _fixture_root(tmp_path, monkeypatch)
    manifest_path = tmp_path / "manifest.json"
    records = package_release.collect_release_files(root)
    manifest_path.write_text(json.dumps({"files": records}), encoding="utf-8")
    zip_path = tmp_path / "release.zip"
    package_release.create_release_zip(zip_path, root=root, manifest_path=manifest_path)
    with zipfile.ZipFile(zip_path) as archive:
        assert set(archive.namelist()) == {"src/main.py", "examples/live_config.example.json"}

    (root / "src" / "main.py").write_text("changed\n", encoding="utf-8")
    with pytest.raises(package_release.PackagingError, match="changed"):
        package_release.create_release_zip(
            tmp_path / "drift.zip", root=root, manifest_path=manifest_path
        )


def test_existing_output_is_not_overwritten(tmp_path, monkeypatch):
    root = _fixture_root(tmp_path, monkeypatch)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"files": package_release.collect_release_files(root)}), encoding="utf-8"
    )
    output = tmp_path / "release.zip"
    output.write_bytes(b"sentinel")
    with pytest.raises(package_release.PackagingError, match="overwrite"):
        package_release.create_release_zip(output, root=root, manifest_path=manifest_path)


def test_public_extras_are_static_and_do_not_depend_on_git():
    payload = json.loads(
        package_release.PUBLIC_EXTRA_MANIFEST.read_text(encoding="utf-8")
    )
    paths = set(payload["files"])
    assert "examples/evaluation/live_config.example.json" in paths
    assert "scripts/package_release.py" in paths
    assert "deliverables/PowerBI_Demo_Refresh_R2/EvidenceBI.pbip" in paths
    assert "deliverables/verification/dashboard_refresh_r2/engine.json" in paths
    assert "deliverables/verification/dashboard_refresh_r2/native-rendering-v2.json" in paths
    assert "deliverables/verification/dashboard_refresh_r2/static-verification.json" not in paths
    assert not any("t15-candidate-verification" in path for path in paths)
    assert package_release.is_included(
        "deliverables/PowerBI_Demo_Candidate/EvidenceBI.pbip"
    )
    assert all("\\" not in path and not path.startswith(("/", "..")) for path in paths)


def test_public_content_scan_rejects_fake_absolute_marker(tmp_path):
    fake_public = tmp_path / "public.json"
    fake_public.write_text(
        '{"note": "C:\\\\Users\\\\fake\\\\private.json"}', encoding="utf-8"
    )
    assert package_release.contains_absolute_machine_path_marker(fake_public.read_bytes())
    safe_public = tmp_path / "safe.json"
    safe_public.write_text('{"note": "https://example.com/schema"}', encoding="utf-8")
    assert not package_release.contains_absolute_machine_path_marker(safe_public.read_bytes())


def test_collect_rejects_selected_json_with_absolute_machine_path(tmp_path, monkeypatch):
    root = _fixture_root(tmp_path, monkeypatch)
    unsafe = root / "examples" / "unsafe.json"
    unsafe.write_text('{"path": "C:\\\\Users\\\\fake\\\\report.json"}\n', encoding="utf-8")
    extra = root / "extras.json"
    extra.write_text(
        json.dumps({"files": ["examples/live_config.example.json", "examples/unsafe.json"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(package_release, "PUBLIC_EXTRA_MANIFEST", extra)
    with pytest.raises(package_release.PackagingError, match="absolute machine path"):
        package_release.collect_release_files(root)
