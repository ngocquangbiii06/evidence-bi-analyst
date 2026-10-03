"""Offline-only readiness checks for the frozen M5 live evaluation batch."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import Field

from .analysis_finalizer import IMPLEMENTATION_VERSION
from .contracts import DataPolicy, Schema, canonical
from .errors import BIError
from .evaluation import (
    FROZEN_ATTEMPT_DENOMINATORS,
    FROZEN_EVALUATION_MANIFEST_SHA256,
    _verify_frozen_manifest,
    run_fixed_workflow_baseline,
)
from .provider import INSTRUCTIONS, Action, strict_schema
from .store import atomic_bytes

CONFIG_SCHEMA_VERSION = "m5-live-evaluation-config-v1"
FIXED_PROVIDER_ID = "openai"
FIXED_ENDPOINT = "https://api.openai.com/v1/responses"
FROZEN_SCENARIO_IDS = tuple(f"E{index:02d}" for index in range(1, 15))
MAX_MODEL_CALLS_PER_ATTEMPT = 16
MAX_OUTPUT_TOKENS_PER_CALL = 1200
MAX_PAYLOAD_BYTES = 32_768


class LiveEvaluationConfig(Schema):
    """Non-secret configuration stub; credential values are never accepted here."""

    config_schema_version: Literal["m5-live-evaluation-config-v1"]
    live_enabled: bool = False
    authorization_reference: str | None = Field(default=None, max_length=160)
    provider_id: str | None = Field(default=None, max_length=40)
    endpoint: str | None = Field(default=None, max_length=200)
    model_id: str | None = Field(default=None, max_length=100)
    model_config_version: str | None = Field(default=None, max_length=100)
    credential_env_var: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{1,79}$")
    runtime_implementation_version: str | None = Field(default=None, max_length=64)
    prompt_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    action_schema_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    evaluation_manifest_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    attempts_per_scenario: int = Field(default=3, ge=1, le=3)
    max_model_calls_per_attempt: int = Field(default=16, ge=1, le=16)
    max_output_tokens_per_call: int = Field(default=1200, ge=64, le=1200)
    max_payload_bytes: int = Field(default=32_768, ge=512, le=32_768)
    input_usd_per_million: Decimal | None = Field(default=None, ge=0)
    output_usd_per_million: Decimal | None = Field(default=None, ge=0)
    per_attempt_budget_usd: Decimal | None = Field(default=None, gt=0)
    batch_budget_usd: Decimal | None = Field(default=None, gt=0)
    output_dir: str = Field(min_length=1, max_length=240)


def load_live_evaluation_config(path: Path) -> LiveEvaluationConfig:
    """Load the bounded non-secret config without interpolating invalid values."""
    try:
        payload = Path(path).read_bytes()
        if len(payload) > 65_536:
            raise ValueError
        return LiveEvaluationConfig.model_validate_json(payload)
    except (OSError, ValueError, TypeError):
        raise BIError(
            "EVALUATION_CONFIG_INVALID",
            "Live evaluation config is missing, malformed, oversized, or has unsupported fields.",
        ) from None


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def current_version_pins() -> dict:
    prompt_hash = _sha256_bytes(INSTRUCTIONS.encode("utf-8"))
    schema_hash = _sha256_bytes(canonical(strict_schema(Action)).encode("utf-8"))
    return {
        "runtime_implementation_version": IMPLEMENTATION_VERSION,
        "prompt_sha256": prompt_hash,
        "action_schema_sha256": schema_hash,
        "evaluation_manifest_sha256": FROZEN_EVALUATION_MANIFEST_SHA256,
    }


def inspect_frozen_evaluation_plan(root: Path) -> dict:
    """Verify all R3-pinned inputs and the exact 14 × 3 planned attempt ledger."""
    root = Path(root)
    manifest_path = root / "examples/evaluation/acceptance_manifest.json"
    scenario_path = root / "examples/evaluation/scenarios.json"
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        _verify_frozen_manifest(root, manifest)
        scenario_bytes = scenario_path.read_bytes()
        scenario_doc = json.loads(scenario_bytes)
        scenarios = scenario_doc["scenarios"]
        attempts = scenario_doc["attempts"]
    except (OSError, ValueError, TypeError, KeyError, BIError):
        raise BIError(
            "EVALUATION_SPEC_INVALID",
            "Frozen evaluation inputs failed integrity or structure checks.",
        ) from None

    scenario_ids = [item.get("id") for item in scenarios if isinstance(item, dict)]
    attempt_ids = [item.get("id") for item in attempts if isinstance(item, dict)]
    counts = Counter(item.get("scenario_id") for item in attempts if isinstance(item, dict))
    planned_exposure = [item.get("planned_model_exposure") for item in attempts]
    expected_counts = {scenario_id: 3 for scenario_id in FROZEN_SCENARIO_IDS}
    plan_valid = (
        scenario_ids == list(FROZEN_SCENARIO_IDS)
        and len(attempts) == FROZEN_ATTEMPT_DENOMINATORS["all"]
        and len(attempt_ids) == len(set(attempt_ids))
        and counts == Counter(expected_counts)
        and all(type(value) is bool for value in planned_exposure)
        and sum(value is True for value in planned_exposure)
        == FROZEN_ATTEMPT_DENOMINATORS["model_exposed"]
    )
    if not plan_valid:
        raise BIError(
            "EVALUATION_SPEC_INVALID",
            "Frozen E01–E14 scenario or attempt denominators do not match the contract.",
        )

    return {
        "status": "passed",
        "manifest_sha256": manifest["canonical_sha256"],
        "manifest_file_sha256": _sha256_bytes(manifest_bytes),
        "scenario_file_sha256": _sha256_bytes(scenario_bytes),
        "scenario_ids": list(FROZEN_SCENARIO_IDS),
        "scenario_count": len(FROZEN_SCENARIO_IDS),
        "attempts_per_scenario": 3,
        "planned_attempt_count": len(attempts),
        "model_exposed_attempt_count": sum(value is True for value in planned_exposure),
        "preflight_blocked_attempt_count": sum(value is False for value in planned_exposure),
        "attempt_denominators": dict(FROZEN_ATTEMPT_DENOMINATORS),
        "manifest_entries": [
            {"path": entry["path"], "sha256": entry["sha256"]}
            for entry in manifest["entries"]
        ],
    }


def _resolve_verification_path(root: Path, configured_path: str) -> tuple[Path | None, str | None]:
    if not isinstance(configured_path, str) or not configured_path.strip():
        return None, None
    path = Path(configured_path)
    if path.is_absolute():
        return None, None
    try:
        resolved_root = root.resolve()
        lexical_verification_root = resolved_root / "deliverables" / "verification"
        verification_root = lexical_verification_root.resolve()
        lexical_path = resolved_root / path
        resolved_path = lexical_path.resolve()
        if os.path.normcase(str(verification_root)) != os.path.normcase(
            str(lexical_verification_root)
        ):
            return None, None
        if not _path_is_within(verification_root, resolved_root):
            return None, None
        if os.path.normcase(str(resolved_path)) != os.path.normcase(str(lexical_path)):
            return None, None
        if not _path_is_within(resolved_path, resolved_root):
            return None, None
        relative_path = resolved_path.relative_to(verification_root)
    except (OSError, ValueError):
        return None, None
    if not relative_path.parts:
        return None, None
    return resolved_path, Path("deliverables/verification", *relative_path.parts).as_posix()


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _path_has_data(path: Path) -> bool:
    if not path.exists():
        return False
    if not path.is_dir():
        return True
    return next(path.iterdir(), None) is not None


def _nonblank(value: str | None) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _evaluation_config_binding(config: LiveEvaluationConfig) -> dict:
    """Fingerprint only non-secret config identity; never inspect credential values."""
    identity = {
        "provider_id": config.provider_id,
        "endpoint": config.endpoint,
        "model_id": config.model_id,
        "model_config_version": config.model_config_version,
        "authorization_reference_sha256": (
            _sha256_bytes(config.authorization_reference.encode("utf-8"))
            if _nonblank(config.authorization_reference)
            else None
        ),
        "credential_env_var_configured": _nonblank(config.credential_env_var),
    }
    return {
        **identity,
        "identity_sha256": _sha256_bytes(
            json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ),
    }


def _cost_estimate(config: LiveEvaluationConfig, model_exposed_attempts: int) -> dict:
    input_rate = config.input_usd_per_million
    output_rate = config.output_usd_per_million
    if input_rate is None or output_rate is None or input_rate <= 0 or output_rate <= 0:
        return {
            "status": "not_computable",
            "currency": "USD",
            "method": "AgentRunner byte-based pre-call reservation, bounded by policy limits",
            "estimated_per_call_usd": None,
            "estimated_per_attempt_usd": None,
            "estimated_batch_usd": None,
            "model_exposed_attempts": model_exposed_attempts,
            "max_model_calls_per_attempt": config.max_model_calls_per_attempt,
        }

    schema_bytes = len(canonical(strict_schema(Action)).encode("utf-8"))
    input_units_per_call = (
        config.max_payload_bytes
        + schema_bytes
        + len(INSTRUCTIONS.encode("utf-8"))
        + 2048
    )
    per_call = (
        Decimal(input_units_per_call) * input_rate
        + Decimal(config.max_output_tokens_per_call) * output_rate
    ) / Decimal(1_000_000)
    per_attempt = per_call * config.max_model_calls_per_attempt
    batch = per_attempt * model_exposed_attempts
    return {
        "status": "computed",
        "currency": "USD",
        "method": "AgentRunner byte-based pre-call reservation, bounded by policy limits",
        "input_units_per_call_ceiling": input_units_per_call,
        "output_tokens_per_call_ceiling": config.max_output_tokens_per_call,
        "estimated_per_call_usd": str(per_call),
        "estimated_per_attempt_usd": str(per_attempt),
        "estimated_batch_usd": str(batch),
        "model_exposed_attempts": model_exposed_attempts,
        "max_model_calls_per_attempt": config.max_model_calls_per_attempt,
    }


def assess_live_readiness(
    root: Path, config: LiveEvaluationConfig, offline_output_dir: str | Path
) -> dict:
    """Assess frozen inputs and config without reading credentials or invoking a provider."""
    root = Path(root).resolve()
    blockers: list[str] = []
    try:
        frozen_plan = inspect_frozen_evaluation_plan(root)
    except BIError:
        frozen_plan = {"status": "failed"}
        blockers.append("frozen_evaluation_integrity_failed")

    versions = current_version_pins()
    configured_version_pins = {
        "runtime_implementation_version": config.runtime_implementation_version,
        "prompt_sha256": config.prompt_sha256,
        "action_schema_sha256": config.action_schema_sha256,
        "evaluation_manifest_sha256": config.evaluation_manifest_sha256,
    }
    version_checks = {
        key: {
            "configured": configured_version_pins[key],
            "current": current,
            "matches": configured_version_pins[key] == current,
        }
        for key, current in versions.items()
    }
    for name, check in version_checks.items():
        if not check["matches"]:
            blockers.append(f"{name}_missing_or_stale")

    if config.attempts_per_scenario != 3:
        blockers.append("attempts_per_scenario_must_remain_three")
    if config.live_enabled is not True:
        blockers.append("explicit_live_opt_in_is_off")
    if not _nonblank(config.authorization_reference):
        blockers.append("live_authorization_reference_missing")
    if config.provider_id != FIXED_PROVIDER_ID:
        blockers.append("provider_not_explicitly_configured")
    if config.endpoint != FIXED_ENDPOINT:
        blockers.append("fixed_provider_endpoint_not_explicitly_configured")
    if not _nonblank(config.model_id):
        blockers.append("evaluation_model_not_approved")
    if not _nonblank(config.model_config_version):
        blockers.append("evaluation_model_config_version_missing")
    if not _nonblank(config.credential_env_var):
        blockers.append("credential_environment_reference_missing")
    if not _nonblank(config.output_dir):
        blockers.append("live_output_dir_missing_or_blank")

    offline_path_text = str(offline_output_dir)
    if Path(offline_path_text).is_absolute():
        try:
            offline_path_text = Path(offline_path_text).resolve().relative_to(root).as_posix()
        except ValueError:
            offline_path_text = ""
    offline_path, offline_relative = _resolve_verification_path(root, offline_path_text)
    live_path, live_relative = _resolve_verification_path(root, config.output_dir)
    if offline_path is None:
        blockers.append("offline_output_path_outside_verification_root")
    output_paths_valid = offline_path is not None and live_path is not None
    if live_path is None:
        blockers.append("live_output_path_outside_verification_root")
    elif offline_path is not None and (
        _path_is_within(live_path, offline_path) or _path_is_within(offline_path, live_path)
    ):
        output_paths_valid = False
        blockers.append("live_and_offline_output_paths_overlap")
    elif _path_has_data(live_path):
        output_paths_valid = False
        blockers.append("live_output_path_already_contains_data")

    if offline_path is not None and _path_has_data(offline_path):
        output_paths_valid = False
        blockers.append("offline_output_path_already_contains_data")

    cost = _cost_estimate(
        config,
        frozen_plan.get("model_exposed_attempt_count", FROZEN_ATTEMPT_DENOMINATORS["model_exposed"]),
    )
    if config.input_usd_per_million is None or config.input_usd_per_million <= 0:
        blockers.append("input_token_rate_missing_or_nonpositive")
    if config.output_usd_per_million is None or config.output_usd_per_million <= 0:
        blockers.append("output_token_rate_missing_or_nonpositive")
    if config.per_attempt_budget_usd is None:
        blockers.append("per_attempt_cost_ceiling_unset")
    if config.batch_budget_usd is None:
        blockers.append("batch_cost_ceiling_unset")
    if cost["status"] == "computed":
        per_attempt_estimate = Decimal(cost["estimated_per_attempt_usd"])
        batch_estimate = Decimal(cost["estimated_batch_usd"])
        if config.per_attempt_budget_usd is not None:
            if config.per_attempt_budget_usd < per_attempt_estimate:
                blockers.append("per_attempt_cost_ceiling_below_estimate")
        if config.batch_budget_usd is not None:
            if config.batch_budget_usd < batch_estimate:
                blockers.append("batch_cost_ceiling_below_estimate")

    default_policy = DataPolicy()
    cloud_default_off = (
        default_policy.mode == "local_only" and default_policy.external_llm_enabled is False
    )
    if not cloud_default_off:
        blockers.append("application_cloud_default_is_not_off")

    blockers = list(dict.fromkeys(blockers))
    offline_checks_pass = (
        frozen_plan.get("status") == "passed"
        and offline_path is not None
        and not any(
            blocker.startswith(("offline_output", "frozen_evaluation")) for blocker in blockers
        )
        and cloud_default_off
    )
    return {
        "schema_version": "1.0",
        "offline_readiness": "ready" if offline_checks_pass else "failed",
        "live_readiness": "blocked_live" if blockers else "ready_for_t18_preflight",
        "blocked_live_reasons": blockers,
        "live_enabled": config.live_enabled,
        "live_invocation_performed": False,
        "acceptance_attempts_performed": 0,
        "attempt_denominator": FROZEN_ATTEMPT_DENOMINATORS["all"],
        "model_exposed_attempt_denominator": FROZEN_ATTEMPT_DENOMINATORS["model_exposed"],
        "provider_calls": 0,
        "model_calls": 0,
        "credential_access": "not_performed",
        "credential_presence": "not_checked",
        "application_cloud_default": {
            "mode": default_policy.mode,
            "external_llm_enabled": default_policy.external_llm_enabled,
            "status": "off" if cloud_default_off else "unexpectedly_enabled",
        },
        "frozen_evaluation": frozen_plan,
        "version_bindings": version_checks,
        "evaluation_config_binding": _evaluation_config_binding(config),
        "cost_estimate_and_ceilings": {
            **cost,
            "configured_per_attempt_budget_usd": (
                str(config.per_attempt_budget_usd)
                if config.per_attempt_budget_usd is not None
                else None
            ),
            "configured_batch_budget_usd": (
                str(config.batch_budget_usd) if config.batch_budget_usd is not None else None
            ),
        },
        "output_paths": {
            "offline_output_dir": offline_relative,
            "live_output_dir": live_relative,
            "paths_validated_under_verification_root": output_paths_valid,
        },
    }


def run_m5_readiness(
    root: Path,
    config_path: Path,
    offline_output_dir: str | Path,
) -> dict:
    """Run a local deterministic dry-run and write a credential-free readiness record."""
    root = Path(root).resolve()
    output_text = str(offline_output_dir)
    if Path(output_text).is_absolute():
        try:
            output_text = Path(output_text).resolve().relative_to(root).as_posix()
        except ValueError:
            raise BIError("UNSAFE_PATH", "Offline output must stay under project verification.") from None
    output_path, _ = _resolve_verification_path(root, output_text)
    if output_path is None:
        raise BIError("UNSAFE_PATH", "Offline output must stay under project verification.")
    if _path_has_data(output_path):
        raise BIError("READINESS_OUTPUT_EXISTS", "Choose a fresh offline verification directory.")

    config = load_live_evaluation_config(Path(config_path))
    readiness = assess_live_readiness(root, config, output_text)
    output_path.mkdir(parents=True, exist_ok=True)

    if readiness["frozen_evaluation"]["status"] == "passed":
        baseline = run_fixed_workflow_baseline(root, output_path / "offline_baseline")
        dry_run = {
            "status": (
                "passed"
                if baseline["batch_status"] == "completed"
                and baseline["baseline_case_count"] == 14
                and baseline["numeric_baseline"]["status"] == "pass"
                and baseline["actual_acceptance_attempts"] == 0
                and baseline["provider_calls"] == 0
                and baseline["model_calls"] == 0
                else "failed"
            ),
            "scenario_count": baseline["baseline_case_count"],
            "attempt_denominator": baseline["attempt_denominator"],
            "batch_status": baseline["batch_status"],
            "numeric_baseline_status": baseline["numeric_baseline"]["status"],
            "actual_acceptance_attempts": baseline["actual_acceptance_attempts"],
            "provider_calls": baseline["provider_calls"],
            "model_calls": baseline["model_calls"],
            "baseline_report_sha256": _sha256_bytes(
                (output_path / "offline_baseline" / "baseline-report.json").read_bytes()
            ),
        }
    else:
        dry_run = {
            "status": "not_run",
            "reason": "frozen_evaluation_integrity_failed",
            "actual_acceptance_attempts": 0,
            "provider_calls": 0,
            "model_calls": 0,
        }

    readiness["offline_dry_run"] = dry_run
    if dry_run["status"] != "passed":
        readiness["offline_readiness"] = "failed"
    report_path = output_path / "readiness-report.json"
    report_payload = json.dumps(readiness, ensure_ascii=False, sort_keys=True, indent=2).encode(
        "utf-8"
    )
    atomic_bytes(report_path, report_payload)
    readiness["readiness_report_sha256"] = _sha256_bytes(report_payload)
    return readiness
