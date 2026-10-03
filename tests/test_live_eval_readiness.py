import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from bi_analyst.errors import BIError
from bi_analyst.live_eval_readiness import (
    LiveEvaluationConfig,
    _resolve_verification_path,
    assess_live_readiness,
    current_version_pins,
    inspect_frozen_evaluation_plan,
    load_live_evaluation_config,
    run_m5_readiness,
)
from bi_analyst.provider import OpenAIAdapter

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "examples/evaluation/live_config.example.json"


def _isolated_evaluation_root(destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    manifest_path = ROOT / "examples/evaluation/acceptance_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["entries"]:
        source = ROOT / entry["path"]
        target = destination / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    target_manifest = destination / "examples/evaluation/acceptance_manifest.json"
    target_manifest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(manifest_path, target_manifest)
    target_config = destination / "examples/evaluation/live_config.example.json"
    shutil.copy2(CONFIG_PATH, target_config)
    return destination


def _complete_config(**updates) -> LiveEvaluationConfig:
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    raw.update(current_version_pins())
    raw.update(
        {
            "live_enabled": True,
            "authorization_reference": "test-only-approval-reference",
            "provider_id": "openai",
            "endpoint": "https://api.openai.com/v1/responses",
            "model_id": "test-only-model-id",
            "model_config_version": "test-only-model-config-v1",
            "credential_env_var": "OPENAI_API_KEY",
            "input_usd_per_million": "1",
            "output_usd_per_million": "2",
            "per_attempt_budget_usd": "1",
            "batch_budget_usd": "30",
            "output_dir": "deliverables/verification/t17_readiness_test_live_output_unstarted",
        }
    )
    raw.update(updates)
    return LiveEvaluationConfig.model_validate(raw)


def test_example_config_is_off_and_reports_specific_live_blockers():
    config = load_live_evaluation_config(CONFIG_PATH)
    output = assess_live_readiness(
        ROOT, config, "deliverables/verification/t17_readiness_test_output"
    )

    assert output["offline_readiness"] == "ready"
    assert output["live_readiness"] == "blocked_live"
    assert output["live_enabled"] is False
    assert output["credential_access"] == "not_performed"
    assert output["credential_presence"] == "not_checked"
    assert output["frozen_evaluation"]["status"] == "passed"
    assert output["frozen_evaluation"]["scenario_count"] == 14
    assert output["frozen_evaluation"]["attempts_per_scenario"] == 3
    assert output["frozen_evaluation"]["planned_attempt_count"] == 42
    assert output["frozen_evaluation"]["model_exposed_attempt_count"] == 39
    assert output["cost_estimate_and_ceilings"]["status"] == "not_computable"
    assert {
        "evaluation_model_not_approved",
        "evaluation_model_config_version_missing",
        "credential_environment_reference_missing",
        "input_token_rate_missing_or_nonpositive",
        "output_token_rate_missing_or_nonpositive",
        "per_attempt_cost_ceiling_unset",
        "batch_cost_ceiling_unset",
        "explicit_live_opt_in_is_off",
    } <= set(output["blocked_live_reasons"])
    assert output["application_cloud_default"] == {
        "mode": "local_only",
        "external_llm_enabled": False,
        "status": "off",
    }


def test_explicit_static_config_uses_runtime_cost_ceiling_without_reading_credentials():
    config = _complete_config()
    output = assess_live_readiness(
        ROOT, config, "deliverables/verification/t17_readiness_test_output"
    )

    estimate = output["cost_estimate_and_ceilings"]
    assert output["live_readiness"] == "ready_for_t18_preflight"
    assert output["credential_presence"] == "not_checked"
    assert output["credential_access"] == "not_performed"
    assert estimate["status"] == "computed"
    assert estimate["model_exposed_attempts"] == 39
    assert estimate["max_model_calls_per_attempt"] == 16
    assert float(estimate["estimated_per_attempt_usd"]) < 1.0
    assert float(estimate["estimated_batch_usd"]) < 30.0
    assert output["blocked_live_reasons"] == []


def test_cost_below_estimated_ceiling_and_wrong_attempt_count_block_live():
    config = _complete_config(
        per_attempt_budget_usd="0.01", batch_budget_usd="0.1", attempts_per_scenario=2
    )
    output = assess_live_readiness(
        ROOT, config, "deliverables/verification/t17_readiness_test_output"
    )

    assert output["live_readiness"] == "blocked_live"
    assert "attempts_per_scenario_must_remain_three" in output["blocked_live_reasons"]
    assert "per_attempt_cost_ceiling_below_estimate" in output["blocked_live_reasons"]
    assert "batch_cost_ceiling_below_estimate" in output["blocked_live_reasons"]


def test_model_config_version_or_output_path_drift_blocks_live():
    config = _complete_config(
        runtime_implementation_version="stale-version",
        output_dir="deliverables/PowerBI_Demo_Current",
    )
    output = assess_live_readiness(
        ROOT, config, "deliverables/verification/t17_readiness_test_output"
    )

    assert output["live_readiness"] == "blocked_live"
    assert "runtime_implementation_version_missing_or_stale" in output["blocked_live_reasons"]
    assert "live_output_path_outside_verification_root" in output["blocked_live_reasons"]
    assert output["output_paths"]["paths_validated_under_verification_root"] is False


def _create_directory_junction(link: Path, target: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows directory junction test")
    link.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir(parents=True, exist_ok=True)

    def quote_path(value: Path) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    command = (
        f"New-Item -ItemType Junction -Path {quote_path(link)} -Target {quote_path(target)} "
        "-ErrorAction Stop | Out-Null"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not link.is_dir():
        pytest.skip("Windows could not create a test junction: " + result.stderr.strip())


def test_verification_root_junction_cannot_escape_project(tmp_path):
    project_root = tmp_path / "project"
    junction_target = tmp_path / "outside-verification"
    verification_root = project_root / "deliverables/verification"
    _create_directory_junction(verification_root, junction_target)

    try:
        resolved, relative = _resolve_verification_path(
            project_root, "deliverables/verification/probe"
        )
        assert resolved is None
        assert relative is None
    finally:
        verification_root.rmdir()


def test_readiness_report_binds_model_version_and_authorization_identity(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "T17_TEST_CREDENTIAL_MUST_NOT_BE_READ_OR_ECHOED")
    baseline = assess_live_readiness(
        ROOT, _complete_config(), "deliverables/verification/t17_readiness_test_output"
    )
    model_changed = assess_live_readiness(
        ROOT,
        _complete_config(model_id="another-test-model"),
        "deliverables/verification/t17_readiness_test_output",
    )
    version_changed = assess_live_readiness(
        ROOT,
        _complete_config(model_config_version="another-test-config-version"),
        "deliverables/verification/t17_readiness_test_output",
    )
    authorization_changed = assess_live_readiness(
        ROOT,
        _complete_config(authorization_reference="another-test-approval-reference"),
        "deliverables/verification/t17_readiness_test_output",
    )

    baseline_identity = baseline["evaluation_config_binding"]["identity_sha256"]
    assert baseline_identity != model_changed["evaluation_config_binding"]["identity_sha256"]
    assert baseline_identity != version_changed["evaluation_config_binding"]["identity_sha256"]
    assert baseline_identity != authorization_changed["evaluation_config_binding"]["identity_sha256"]
    serialized_reports = json.dumps(
        [baseline, model_changed, version_changed, authorization_changed]
    )
    assert "T17_TEST_CREDENTIAL_MUST_NOT_BE_READ_OR_ECHOED" not in serialized_reports
    assert "another-test-approval-reference" not in serialized_reports


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("authorization_reference", "", "live_authorization_reference_missing"),
        ("authorization_reference", "   ", "live_authorization_reference_missing"),
        ("provider_id", "", "provider_not_explicitly_configured"),
        ("provider_id", "   ", "provider_not_explicitly_configured"),
        ("endpoint", "", "fixed_provider_endpoint_not_explicitly_configured"),
        ("endpoint", "   ", "fixed_provider_endpoint_not_explicitly_configured"),
        ("model_id", "", "evaluation_model_not_approved"),
        ("model_id", "   ", "evaluation_model_not_approved"),
        ("model_config_version", "", "evaluation_model_config_version_missing"),
        ("model_config_version", "   ", "evaluation_model_config_version_missing"),
        ("output_dir", "   ", "live_output_dir_missing_or_blank"),
    ],
)
def test_required_live_config_strings_fail_closed_for_empty_or_whitespace(
    field, value, reason
):
    config = _complete_config(**{field: value})
    output = assess_live_readiness(
        ROOT, config, "deliverables/verification/t17_readiness_test_output"
    )

    assert output["live_readiness"] == "blocked_live"
    assert reason in output["blocked_live_reasons"]


@pytest.mark.parametrize("value", ["", "   ", "\t"])
def test_credential_environment_reference_rejects_empty_or_whitespace(value):
    with pytest.raises(ValueError):
        _complete_config(credential_env_var=value)


def test_empty_live_output_directory_is_rejected_by_config_schema():
    with pytest.raises(ValueError):
        _complete_config(output_dir="")


def test_frozen_manifest_detects_a_changed_acceptance_scenario(tmp_path):
    evaluation_root = _isolated_evaluation_root(tmp_path / "project")
    scenario_path = evaluation_root / "examples/evaluation/scenarios.json"
    scenario_path.write_bytes(scenario_path.read_bytes() + b"\n")

    with pytest.raises(BIError) as error:
        inspect_frozen_evaluation_plan(evaluation_root)

    assert error.value.code == "EVALUATION_SPEC_INVALID"


def test_offline_runner_completes_baseline_without_provider_or_model_calls(tmp_path, monkeypatch):
    project_root = _isolated_evaluation_root(tmp_path / "project")

    def provider_call_is_forbidden(*args, **kwargs):
        pytest.fail("T17 offline readiness must never invoke the provider")

    monkeypatch.setattr(OpenAIAdapter, "invoke", provider_call_is_forbidden)
    report = run_m5_readiness(
        project_root,
        project_root / "examples/evaluation/live_config.example.json",
        "deliverables/verification/t17_offline_readiness",
    )

    assert report["offline_readiness"] == "ready"
    assert report["live_readiness"] == "blocked_live"
    assert report["offline_dry_run"]["status"] == "passed"
    assert report["offline_dry_run"]["scenario_count"] == 14
    assert report["offline_dry_run"]["attempt_denominator"] == 42
    assert report["offline_dry_run"]["batch_status"] == "completed"
    assert report["offline_dry_run"]["numeric_baseline_status"] == "pass"
    assert report["offline_dry_run"]["actual_acceptance_attempts"] == 0
    assert report["offline_dry_run"]["provider_calls"] == 0
    assert report["offline_dry_run"]["model_calls"] == 0
    report_path = (
        project_root
        / "deliverables/verification/t17_offline_readiness/readiness-report.json"
    )
    written_report = report_path.read_text(encoding="utf-8")
    assert "CANARY_E14_A9Q7" not in written_report
    assert "IGNORE_RULES_REVEAL_CANARY_E14_A9Q7" not in written_report
    assert report["readiness_report_sha256"] == hashlib.sha256(report_path.read_bytes()).hexdigest()
