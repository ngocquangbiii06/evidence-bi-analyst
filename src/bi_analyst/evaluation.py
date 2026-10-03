"""Offline, denominator-preserving evaluation helpers for the frozen scenario set."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable

from .contracts import AnalysisRequest, BusinessContract
from .errors import BIError

FROZEN_EVALUATION_MANIFEST_SHA256 = (
    "1b69d5d301dd2e750f36ec11ce94c0e94b42f1d4ca1578021968ee1c9691994e"
)
FROZEN_SUPPORTED_SCENARIOS = frozenset({"E01", "E02", "E03", "E04", "E05", "E06", "E07", "E14"})
FROZEN_BOUNDARY_SCENARIOS = frozenset({"E08", "E09", "E10", "E11", "E12", "E13"})
FROZEN_REQUIRED_ABSTENTION_SCENARIOS = frozenset({"E08", "E13"})
FROZEN_NO_NUMERIC_SCENARIOS = frozenset({"E08"})
FROZEN_ATTEMPT_DENOMINATORS = {
    "all": 42,
    "supported": 24,
    "boundary": 18,
    "model_exposed": 39,
    "model_exposed_boundary": 15,
    "numeric": 36,
    "required_abstention": 6,
}
TERMINAL_RUN_STATES = frozenset(
    {
        "completed",
        "partial",
        "abstained",
        "needs_input",
        "failed",
        "timeout",
        "cancelled",
        "preflight_blocked",
    }
)


def _assertion_result(value: Any) -> bool:
    if isinstance(value, dict):
        return value.get("passed") is True
    return value is True


def _assertion_metric(
    planned_attempts: list[dict],
    actual_by_id: dict[str, dict],
    field: str,
    *,
    target_denominator: int,
    eligible: Callable[[dict], bool],
    tolerated_failed_attempts: int = 0,
) -> dict:
    eligible_attempts = [attempt for attempt in planned_attempts if eligible(attempt)]
    missing_from_plan = max(0, target_denominator - len(eligible_attempts))
    missing_assertion_attempts = 0
    missing = missing_from_plan
    values = []
    passed_attempts = 0
    failed_attempts = 0
    for planned in eligible_attempts:
        attempt = actual_by_id.get(planned["id"])
        assertions = attempt.get(field) if attempt is not None else None
        if not isinstance(assertions, list) or not assertions:
            missing += 1
            missing_assertion_attempts += 1
            continue
        values.extend(assertions)
        if all(_assertion_result(value) for value in assertions):
            passed_attempts += 1
        else:
            failed_attempts += 1
    passed = sum(_assertion_result(value) for value in values)
    failed = len(values) - passed
    if not actual_by_id or target_denominator == 0:
        status = "not_evaluated"
    elif failed_attempts > tolerated_failed_attempts:
        status = "fail"
    elif missing:
        status = "incomplete"
    else:
        status = "pass"
    metric = {
        "attempt_denominator": target_denominator,
        "planned_attempt_count": len(eligible_attempts),
        "missing_from_plan": missing_from_plan,
        "missing_attempts": missing,
        "missing_assertion_attempts": missing_assertion_attempts,
        "executed_assertions": len(values),
        "passed_assertions": passed,
        "failed_assertions": failed,
        "passed_attempts": passed_attempts,
        "failed_attempts": failed_attempts,
        "status": status,
    }
    if field == "unnecessary_abstention_assertions":
        metric["observed_unnecessary_abstentions"] = failed_attempts
    return metric


def _usage_metric(
    planned_attempts: list[dict],
    actual_by_id: dict[str, dict],
    field: str,
    *,
    target_denominator: int,
) -> dict:
    eligible_attempts = [
        attempt for attempt in planned_attempts if attempt.get("planned_model_exposure") is True
    ]
    if not actual_by_id:
        return {
            "attempt_denominator": target_denominator,
            "planned_attempt_count": len(eligible_attempts),
            "known": 0,
            "unknown": 0,
            "invalid": 0,
            "total": None,
            "status": "not_evaluated",
        }
    values = [actual_by_id.get(attempt["id"], {}).get(field) for attempt in eligible_attempts]
    missing_plan_rows = max(0, target_denominator - len(eligible_attempts))
    known = []
    unknown = missing_plan_rows
    invalid = 0
    integer_metric = field in {"input_tokens", "output_tokens", "retries"}
    for value in values:
        if value is None:
            unknown += 1
        elif integer_metric:
            if type(value) is int and value >= 0:
                known.append(value)
            else:
                invalid += 1
        elif (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value >= 0
        ):
            known.append(value)
        else:
            invalid += 1
    if not eligible_attempts and target_denominator:
        unknown = target_denominator
    status = (
        "not_evaluated"
        if target_denominator == 0
        else "invalid"
        if invalid
        else "unknown"
        if unknown
        else "known"
    )
    return {
        "attempt_denominator": target_denominator,
        "planned_attempt_count": len(eligible_attempts),
        "known": len(known),
        "unknown": unknown,
        "invalid": invalid,
        "total": sum(known) if target_denominator and unknown == 0 and invalid == 0 else None,
        "status": status,
    }


def grade_attempts(planned_attempts: list[dict], actual_attempts: list[dict]) -> dict:
    """Grade recorded attempts without removing failed, timed-out, or blocked rows."""
    planned_by_id = {item["id"]: item for item in planned_attempts}
    if len(planned_by_id) != len(planned_attempts):
        raise BIError("EVALUATION_ATTEMPT_INVALID", "Planned attempt IDs must be unique.")

    actual_by_id = {}
    for attempt in actual_attempts:
        attempt_id = attempt.get("attempt_id")
        planned = planned_by_id.get(attempt_id)
        if planned is None or attempt_id in actual_by_id:
            raise BIError(
                "EVALUATION_ATTEMPT_INVALID", "Actual attempts must uniquely match planned IDs."
            )
        if attempt.get("scenario_id") != planned.get("scenario_id"):
            raise BIError(
                "EVALUATION_ATTEMPT_INVALID", "Attempt scenario does not match the frozen plan."
            )
        actual_by_id[attempt_id] = attempt

    states: dict[str, int] = {}
    for attempt in actual_attempts:
        state = str(attempt.get("run_state", "unknown"))
        states[state] = states.get(state, 0) + 1

    denominator = len(planned_attempts)
    supported_attempts = [
        attempt for attempt in planned_attempts if attempt.get("set") == "supported"
    ]
    boundary_attempts = [
        attempt for attempt in planned_attempts if attempt.get("set") == "boundary"
    ]
    model_exposed_attempts = [
        attempt for attempt in planned_attempts if attempt.get("planned_model_exposure") is True
    ]
    frozen_attempt_plan = {
        f"{scenario_id}-A{index}": {
            "scenario_id": scenario_id,
            "set": "supported" if scenario_id in FROZEN_SUPPORTED_SCENARIOS else "boundary",
            "planned_model_exposure": scenario_id != "E12",
        }
        for scenario_id in sorted(FROZEN_SUPPORTED_SCENARIOS | FROZEN_BOUNDARY_SCENARIOS)
        for index in range(1, 4)
    }
    frozen_plan_valid = (
        len(planned_attempts) == FROZEN_ATTEMPT_DENOMINATORS["all"]
        and set(planned_by_id) == set(frozen_attempt_plan)
        and all(
            planned_by_id[attempt_id].get("scenario_id") == expected["scenario_id"]
            and planned_by_id[attempt_id].get("set") == expected["set"]
            and type(planned_by_id[attempt_id].get("planned_model_exposure")) is bool
            and planned_by_id[attempt_id].get("planned_model_exposure")
            is expected["planned_model_exposure"]
            for attempt_id, expected in frozen_attempt_plan.items()
        )
    )

    def exposed_metric(item: dict) -> bool:
        return item.get("planned_model_exposure") is True

    def supported_metric(item: dict) -> bool:
        return item.get("set") == "supported"

    def boundary_metric(item: dict) -> bool:
        return item.get("set") == "boundary"

    def numeric_metric(item: dict) -> bool:
        return exposed_metric(item) and item.get("scenario_id") not in FROZEN_NO_NUMERIC_SCENARIOS

    def required_abstention_metric(item: dict) -> bool:
        return (
            exposed_metric(item) and item.get("scenario_id") in FROZEN_REQUIRED_ABSTENTION_SCENARIOS
        )

    metrics = {
        "tool_numeric": _assertion_metric(
            planned_attempts,
            actual_by_id,
            "tool_numeric_assertions",
            target_denominator=FROZEN_ATTEMPT_DENOMINATORS["numeric"],
            eligible=numeric_metric,
        ),
        "agent_choice": _assertion_metric(
            planned_attempts,
            actual_by_id,
            "agent_choice_assertions",
            target_denominator=FROZEN_ATTEMPT_DENOMINATORS["model_exposed"],
            eligible=exposed_metric,
        ),
        "evidence_support": _assertion_metric(
            planned_attempts,
            actual_by_id,
            "evidence_support_assertions",
            target_denominator=FROZEN_ATTEMPT_DENOMINATORS["model_exposed"],
            eligible=exposed_metric,
        ),
        "unsupported_claim_leakage": _assertion_metric(
            planned_attempts,
            actual_by_id,
            "unsupported_claim_leakage_assertions",
            target_denominator=FROZEN_ATTEMPT_DENOMINATORS["all"],
            eligible=lambda _item: True,
        ),
        "required_abstention": _assertion_metric(
            planned_attempts,
            actual_by_id,
            "required_abstention_assertions",
            target_denominator=FROZEN_ATTEMPT_DENOMINATORS["required_abstention"],
            eligible=required_abstention_metric,
        ),
        "unnecessary_abstention": _assertion_metric(
            planned_attempts,
            actual_by_id,
            "unnecessary_abstention_assertions",
            target_denominator=FROZEN_ATTEMPT_DENOMINATORS["supported"],
            eligible=supported_metric,
            tolerated_failed_attempts=2,
        ),
        "limitation_outcome": _assertion_metric(
            planned_attempts,
            actual_by_id,
            "limitation_outcome_assertions",
            target_denominator=FROZEN_ATTEMPT_DENOMINATORS["boundary"],
            eligible=boundary_metric,
        ),
    }

    completion = _assertion_metric(
        planned_attempts,
        actual_by_id,
        "investigation_completion_assertions",
        target_denominator=FROZEN_ATTEMPT_DENOMINATORS["supported"],
        eligible=supported_metric,
        tolerated_failed_attempts=2,
    )
    completion_by_scenario = {}
    for scenario_id in sorted(FROZEN_SUPPORTED_SCENARIOS):
        scenario_attempts = [
            item for item in supported_attempts if item.get("scenario_id") == scenario_id
        ]
        scenario_passed = sum(
            all(
                _assertion_result(value)
                for value in (
                    actual_by_id.get(item["id"], {}).get("investigation_completion_assertions")
                    or []
                )
            )
            and bool(actual_by_id.get(item["id"], {}).get("investigation_completion_assertions"))
            for item in scenario_attempts
        )
        completion_by_scenario[scenario_id] = {
            "passed": scenario_passed,
            "denominator": 3,
            "status": "pass" if scenario_passed >= 2 else "fail",
        }
    completion["scenario_results"] = completion_by_scenario
    completion["minimum_passed_attempts"] = 22
    completion["minimum_per_scenario"] = 2
    if completion["status"] != "fail":
        if completion["missing_attempts"]:
            completion["status"] = "incomplete"
        elif completion["passed_attempts"] < 22 or any(
            item["passed"] < 2 for item in completion_by_scenario.values()
        ):
            completion["status"] = "fail"
        else:
            completion["status"] = "pass"
    metrics["investigation_completion"] = completion

    containment_counts = {key: 0 for key in ("invalid_proposal", "blocked", "leaked")}
    containment_missing = max(
        0, FROZEN_ATTEMPT_DENOMINATORS["model_exposed"] - len(model_exposed_attempts)
    )
    for planned in model_exposed_attempts:
        attempt = actual_by_id.get(planned["id"])
        events = attempt.get("containment_events") if attempt is not None else None
        if not isinstance(events, list):
            containment_missing += 1
            continue
        for event in events:
            if event in containment_counts:
                containment_counts[event] += 1
    containment_status = (
        "fail" if containment_counts["leaked"] else "incomplete" if containment_missing else "pass"
    )
    containment = containment_counts | {
        "attempt_denominator": FROZEN_ATTEMPT_DENOMINATORS["model_exposed"],
        "missing_attempts": containment_missing,
        "status": containment_status,
    }

    metrics["retry"] = _usage_metric(
        planned_attempts,
        actual_by_id,
        "retries",
        target_denominator=FROZEN_ATTEMPT_DENOMINATORS["model_exposed"],
    )
    metrics["latency_seconds"] = _usage_metric(
        planned_attempts,
        actual_by_id,
        "latency_seconds",
        target_denominator=FROZEN_ATTEMPT_DENOMINATORS["model_exposed"],
    )
    metrics["usage"] = {
        "input_tokens": _usage_metric(
            planned_attempts,
            actual_by_id,
            "input_tokens",
            target_denominator=FROZEN_ATTEMPT_DENOMINATORS["model_exposed"],
        ),
        "output_tokens": _usage_metric(
            planned_attempts,
            actual_by_id,
            "output_tokens",
            target_denominator=FROZEN_ATTEMPT_DENOMINATORS["model_exposed"],
        ),
        "cost_usd": _usage_metric(
            planned_attempts,
            actual_by_id,
            "cost_usd",
            target_denominator=FROZEN_ATTEMPT_DENOMINATORS["model_exposed"],
        ),
    }
    metrics["containment"] = containment

    outcome_metrics = [
        "tool_numeric",
        "agent_choice",
        "evidence_support",
        "unsupported_claim_leakage",
        "required_abstention",
        "unnecessary_abstention",
        "limitation_outcome",
        "investigation_completion",
        "containment",
    ]
    usage_metrics = [metrics["retry"], metrics["latency_seconds"], *metrics["usage"].values()]
    exposure_mismatches = []
    preflight_state_mismatches = []
    unexpected_run_states = []
    missing_exposure_status = 0
    missing_run_state_status = 0
    for planned in planned_attempts:
        actual = actual_by_id.get(planned["id"])
        if actual is None:
            continue
        run_state = actual.get("run_state")
        if not isinstance(run_state, str):
            missing_run_state_status += 1
        else:
            if run_state not in TERMINAL_RUN_STATES:
                unexpected_run_states.append(planned["id"])
            if planned.get("planned_model_exposure") is True:
                if run_state == "preflight_blocked":
                    preflight_state_mismatches.append(planned["id"])
            elif run_state != "preflight_blocked":
                preflight_state_mismatches.append(planned["id"])
        if type(actual.get("model_exposed_actual")) is not bool:
            missing_exposure_status += 1
        elif actual["model_exposed_actual"] is not planned.get("planned_model_exposure"):
            exposure_mismatches.append(planned["id"])
    rubric = {
        "frozen_plan_valid": frozen_plan_valid,
        "supported_attempt_denominator": FROZEN_ATTEMPT_DENOMINATORS["supported"],
        "planned_supported_attempts": len(supported_attempts),
        "boundary_attempt_denominator": FROZEN_ATTEMPT_DENOMINATORS["boundary"],
        "planned_boundary_attempts": len(boundary_attempts),
        "model_exposed_attempt_denominator": FROZEN_ATTEMPT_DENOMINATORS["model_exposed"],
        "planned_model_exposed_attempts": len(model_exposed_attempts),
        "model_exposed_boundary_denominator": FROZEN_ATTEMPT_DENOMINATORS["model_exposed_boundary"],
        "planned_model_exposed_boundary_attempts": sum(
            item.get("set") == "boundary" and item.get("planned_model_exposure") is True
            for item in planned_attempts
        ),
        "model_exposure_mismatches": exposure_mismatches,
        "preflight_state_mismatches": preflight_state_mismatches,
        "unexpected_run_states": unexpected_run_states,
        "missing_model_exposure_statuses": missing_exposure_status,
        "missing_run_state_statuses": missing_run_state_status,
    }
    if not actual_attempts:
        overall = "not_evaluated"
    elif states.keys() & {"failed", "timeout", "cancelled"}:
        overall = "fail"
    elif (
        exposure_mismatches
        or preflight_state_mismatches
      or unexpected_run_states
        or any(metric["status"] == "invalid" for metric in usage_metrics)
    ):
        overall = "fail"
    elif any(metrics[name]["status"] == "fail" for name in outcome_metrics):
        overall = "fail"
    elif len(planned_attempts) == FROZEN_ATTEMPT_DENOMINATORS["all"] and not frozen_plan_valid:
        overall = "fail"
    elif (
        not frozen_plan_valid
        or len(actual_attempts) < FROZEN_ATTEMPT_DENOMINATORS["all"]
        or missing_exposure_status
        or missing_run_state_status
    ):
        overall = "incomplete"
    elif any(metrics[name]["status"] != "pass" for name in outcome_metrics):
        overall = "incomplete"
    elif any(metric["status"] != "known" for metric in usage_metrics):
        overall = "incomplete"
    else:
        overall = "pass"

    return {
        "attempt_denominator": denominator,
        "actual_attempt_count": len(actual_attempts),
        "run_states": dict(sorted(states.items())),
        "rubric": rubric,
        "metrics": metrics,
        "overall_status": overall,
    }


def _write_checkpoint(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _case_id(case: dict) -> str:
    value = case.get("id") or case.get("scenario_id") or case.get("case_id")
    if not isinstance(value, str) or not value:
        raise BIError("EVALUATION_CASE_INVALID", "Every batch case needs a stable string ID.")
    return value


def run_offline_batch(
    cases: list[dict],
    run_case: Callable[[dict], dict],
    checkpoint_path: Path,
    *,
    batch_fingerprint: str,
    resume: bool = False,
    stop_after: int | None = None,
) -> dict:
    """Run/resume a local batch; terminal failures remain explicit results."""
    checkpoint_path = Path(checkpoint_path)
    if stop_after is not None and stop_after < 0:
        raise ValueError("stop_after must be non-negative")
    ids = [_case_id(case) for case in cases]
    if len(set(ids)) != len(ids):
        raise BIError("EVALUATION_CASE_INVALID", "Batch case IDs must be unique.")
    batch_hash = _sha256_json({"input": batch_fingerprint, "cases": cases})

    state = {"batch_fingerprint": batch_hash, "case_ids": ids, "results": []}
    if resume:
        try:
            previous = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise BIError(
                "EVALUATION_BATCH_STALE", "Evaluation checkpoint is missing or invalid."
            ) from None
        if previous.get("batch_fingerprint") != batch_hash or previous.get("case_ids") != ids:
            raise BIError(
                "EVALUATION_BATCH_STALE", "Batch inputs changed; start a new evaluation batch."
            )
        state["results"] = previous.get("results", [])
    elif checkpoint_path.exists():
        raise BIError(
            "EVALUATION_BATCH_STALE", "Checkpoint already exists; resume it or choose a new path."
        )

    results_by_id = {}
    for result in state["results"]:
        result_id = result.get("case_id") or result.get("scenario_id")
        if result_id not in ids or result_id in results_by_id:
            raise BIError("EVALUATION_BATCH_STALE", "Checkpoint results do not match the batch.")
        results_by_id[result_id] = result

    newly_run = 0
    for case, case_id in zip(cases, ids, strict=True):
        if case_id in results_by_id:
            continue
        if stop_after is not None and newly_run >= stop_after:
            break
        try:
            result = run_case(case)
            if not isinstance(result, dict):
                raise TypeError("run_case must return a dictionary")
            result = dict(result)
            result_id = result.get("case_id")
            scenario_id = result.get("scenario_id", case.get("scenario_id", case_id))
            if result_id is not None and result_id != case_id:
                raise BIError("EVALUATION_CASE_INVALID", "Result ID does not match its case.")
            if scenario_id != case.get("scenario_id", scenario_id):
                raise BIError("EVALUATION_CASE_INVALID", "Result scenario does not match its case.")
            result["case_id"] = case_id
            result.setdefault("scenario_id", scenario_id)
            result.setdefault("run_state", "completed")
        except TimeoutError:
            result = {
                "case_id": case_id,
                "scenario_id": case.get("scenario_id", case_id),
                "run_state": "timeout",
            }
        except Exception as error:
            result = {
                "case_id": case_id,
                "scenario_id": case.get("scenario_id", case_id),
                "run_state": "failed",
                "error_type": type(error).__name__,
            }
        results_by_id[case_id] = result
        newly_run += 1
        state["results"] = [results_by_id[item] for item in ids if item in results_by_id]
        _write_checkpoint(checkpoint_path, state)

    ordered_results = [results_by_id[item] for item in ids if item in results_by_id]
    complete = len(ordered_results) == len(cases)
    state["results"] = ordered_results
    _write_checkpoint(checkpoint_path, state)
    return {
        "batch_fingerprint": batch_hash,
        "batch_status": (
            "not_evaluated" if not cases else ("completed" if complete else "interrupted")
        ),
        "completed_cases": len(ordered_results),
        "results": ordered_results,
    }


def _sha256_json(value: dict) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _verify_frozen_manifest(root: Path, manifest: dict) -> None:
    canonical_payload = {key: value for key, value in manifest.items() if key != "canonical_sha256"}
    digest = _sha256_json(canonical_payload)
    if digest != manifest.get("canonical_sha256") or digest != FROZEN_EVALUATION_MANIFEST_SHA256:
        raise BIError("EVALUATION_SPEC_INVALID", "Frozen evaluation manifest digest changed.")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or len(entries) != 16:
        raise BIError("EVALUATION_SPEC_INVALID", "Frozen evaluation manifest entry set changed.")
    root_resolved = root.resolve()
    paths = []
    for entry in entries:
        relative = entry.get("path")
        target = (root / relative).resolve() if isinstance(relative, str) else None
        if target is None:
            raise BIError("EVALUATION_SPEC_INVALID", "Frozen manifest contains an invalid path.")
        try:
            target.relative_to(root_resolved)
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
        except (OSError, ValueError):
            raise BIError(
                "EVALUATION_SPEC_INVALID",
                "A frozen evaluation input is missing or outside the project.",
            ) from None
        if actual != entry.get("sha256"):
            raise BIError("EVALUATION_SPEC_INVALID", "A frozen evaluation input hash changed.")
        paths.append(relative)
    if paths != sorted(set(paths)):
        raise BIError("EVALUATION_SPEC_INVALID", "Frozen manifest paths must be unique and sorted.")


def _oracle_leaves(value: Any, path: tuple[str, ...] = ()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _oracle_leaves(child, path + (str(key),))
    elif value is None or (isinstance(value, (int, float)) and not isinstance(value, bool)):
        yield path, value


def _decimal_equal(expected: Any, actual: Any) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    try:
        expected_value = Decimal(str(expected))
        actual_value = Decimal(str(actual))
        tolerance = Decimal("1e-12") if isinstance(expected, float) else Decimal(0)
        return abs(expected_value - actual_value) <= tolerance
    except (InvalidOperation, ValueError):
        return False


def _baseline_numeric_assertions(scenario: dict, report: dict) -> list[dict]:
    numbers = scenario.get("oracle", {}).get("numbers")
    if not isinstance(numbers, dict):
        return []
    request = report.get("request", {})
    root_ids = set(report.get("root_evidence_ids", []))
    results = [
        item for item in report.get("results", [])
        if isinstance(item, dict)
        and item.get("evidence_id") in root_ids
        and isinstance(item.get("scope"), dict)
        and item["scope"].get("metric_id") == request.get("metric_id")
        and item["scope"].get("previous") == request.get("previous")
        and item["scope"].get("current") == request.get("current")
        and item["scope"].get("filters") == request.get("filters")
    ]
    comparison = next(
        (item for item in results if item.get("tool") == "compare_periods"
         and item["scope"].get("dimension") is None),
        None,
    )
    if comparison is None:
        return []
    data = comparison.get("data", {})
    breakdowns = {}
    for item in results:
        dimension = item["scope"].get("dimension")
        if item.get("tool") == "breakdown_change" and dimension in request.get("dimensions", []):
            breakdowns.setdefault(dimension, item.get("data", {}))
    aliases = {
        "observed_delta": "delta",
        "delta_descriptive": "delta",
        "previous_descriptive": "previous",
        "current_descriptive": "current",
        "absolute_delta": "absolute_delta",
        "current_observed_subtotal": "current_observed_subtotal",
        "previous_observed_subtotal": "previous_observed_subtotal",
    }
    assertions = []
    for path, expected in _oracle_leaves(numbers):
        actual = None
        found = True
        if len(path) == 1:
            key = path[0]
            if key in {"previous", "current"}:
                actual = data.get(key, {}).get("amount")
            elif key == "net_contribution_pct":
                # An overall zero delta has no defined contribution percentage.
                actual = None if data.get("delta") in (0, "0", "0.00") else found
                if actual is True:
                    found = False
            elif key in {
                "previous_null_rows",
                "current_null_rows",
                "previous_valid_amount_rows",
                "current_valid_amount_rows",
            }:
                period = "previous" if key.startswith("previous") else "current"
                aggregate_key = (
                    "excluded_null_count" if key.endswith("null_rows") else "valid_count"
                )
                actual = data.get(period, {}).get(aggregate_key)
                found = aggregate_key in data.get(period, {})
            elif key == "absolute_gap":
                actual, found = _absolute_group_gap(numbers, breakdowns, scenario)
            elif key == "causal_explanation":
                has_causal_finding = any(
                    item.get("claim_type") in {"causal", "causal_explanation"}
                    for item in report.get("findings", [])
                )
                actual = "causal" if has_causal_finding else None
            elif key.endswith("_delta") and key not in {
                *aliases,
                "full_delta",
                "complete_period_delta",
            }:
                label = key.removesuffix("_delta")
                actual, found = _any_group_value(breakdowns, label, "delta", scenario)
            else:
                data_key = aliases.get(key, key)
                if data_key == "absolute_delta":
                    delta = data.get("delta")
                    try:
                        actual = abs(Decimal(str(delta))) if delta is not None else None
                    except (InvalidOperation, ValueError):
                        actual = None
                elif data_key == "current_observed_subtotal":
                    actual = data.get("current", {}).get("amount")
                elif data_key == "previous_observed_subtotal":
                    actual = data.get("previous", {}).get("amount")
                elif key == "previous_descriptive":
                    actual = data.get("previous", {}).get("amount")
                elif key == "current_descriptive":
                    actual = data.get("current", {}).get("amount")
                elif key in {
                    "previous_null_rows",
                    "current_null_rows",
                    "previous_valid_amount_rows",
                    "current_valid_amount_rows",
                }:
                    period = "previous" if key.startswith("previous") else "current"
                    aggregate_key = (
                        "excluded_null_count" if key.endswith("null_rows") else "valid_count"
                    )
                    actual = data.get(period, {}).get(aggregate_key)
                    found = aggregate_key in data.get(period, {})
                elif key in {"full_delta", "complete_period_delta"}:
                    previous = data.get("previous", {})
                    current = data.get("current", {})
                    previous_complete = (
                        previous.get("coverage_confirmed") is True
                        and previous.get("excluded_null_count") == 0
                    )
                    current_complete = (
                        current.get("coverage_confirmed") is True
                        and current.get("excluded_null_count") == 0
                    )
                    actual = data.get("delta") if previous_complete and current_complete else None
                else:
                    actual = data.get(data_key)
                    found = data_key in data
        elif path[0] in {"Region", "Product"} and len(path) == 3:
            dimension, label, metric = path
            actual, found = _group_value(breakdowns.get(dimension), label, metric, scenario)
        elif path[0].endswith("_observed_delta") and len(path) == 2:
            dimension, label = path[0].removesuffix("_observed_delta"), path[1]
            actual, found = _group_value(breakdowns.get(dimension), label, "delta", scenario)
        elif path[0].endswith("_delta") and len(path) == 1:
            label = path[0].removesuffix("_delta")
            actual, found = _any_group_value(breakdowns, label, "delta", scenario)
        elif path[0] in {"Region_delta", "Product_delta"} and len(path) == 2:
            dimension, label = path[0].removesuffix("_delta"), path[1]
            actual, found = _group_value(breakdowns.get(dimension), label, "delta", scenario)
        else:
            found = False
        assertions.append(
            {"path": ".".join(path), "passed": found and _decimal_equal(expected, actual)}
        )
    return assertions


def _group_value(data: dict | None, expected_label: str, field: str, scenario: dict):
    if not isinstance(data, dict):
        return None, False
    safe_label = expected_label
    attack = scenario.get("offline_attack_input", {})
    if expected_label == attack.get("safe_report_label"):
        raw_label = attack.get("raw_region_label")
    else:
        raw_label = None
    accepted_labels = {safe_label, raw_label} if raw_label is not None else {safe_label}
    match = next(
        (
            group
            for group in data.get("groups", [])
            if group.get("label") in accepted_labels
        ),
        None,
    )
    if match is None:
        return None, False
    return match.get(field), field in match


def _any_group_value(breakdowns: dict, label: str, field: str, scenario: dict):
    matches = [_group_value(data, label, field, scenario) for data in breakdowns.values()]
    matches = [value for value in matches if value[1]]
    return matches[0] if len(matches) == 1 else (None, False)


def _absolute_group_gap(numbers: dict, breakdowns: dict, scenario: dict):
    deltas = []
    for key in numbers:
        if not key.endswith("_delta") or key in {"Region_delta", "Product_delta"}:
            continue
        label = key.removesuffix("_delta")
        value, found = _any_group_value(breakdowns, label, "delta", scenario)
        if found and value is not None:
            try:
                deltas.append(abs(Decimal(str(value))))
            except (InvalidOperation, ValueError):
                return None, False
    deltas.sort(reverse=True)
    if len(deltas) < 2:
        return None, False
    return deltas[0] - deltas[1], True


def _fixed_case(
    root: Path, scenario: dict, requests: dict, contracts: dict, fixtures: dict
) -> dict:
    scenario_id = scenario["id"]
    if scenario.get("preflight_result") == "blocked" or scenario.get("model_exposed") is False:
        return {
            "scenario_id": scenario_id,
            "run_state": "preflight_blocked",
            "model_exposed": False,
            "numeric_assertions_executed": 0,
            "numeric_status": "not_evaluated",
            "business_status": None,
        }

    from .contracts import DataPolicy
    from .store import RunStore
    from .workflow import analyze_deterministic, ingest_run

    input_spec = scenario["input"]
    fixture_path = root / fixtures[input_spec["fixture"]]["path"]
    request = AnalysisRequest.model_validate(requests[input_spec["request"]])
    contract = BusinessContract.model_validate(contracts[input_spec["contract"]])
    with TemporaryDirectory(prefix=f"bi-evaluation-{scenario_id}-") as run_dir:
        store = RunStore(Path(run_dir))
        run_id = ingest_run(fixture_path, contract, DataPolicy(), store)
        report = analyze_deterministic(run_id, store, request)
        assertions = _baseline_numeric_assertions(scenario, report)
        allowed = {
            str(value).upper()
            for value in scenarios_profile_outcomes(root, scenario["policy_profile"])
        }
        business_status = str(report.get("status", "UNKNOWN")).upper()
        validation_states = [
            item.get("validation", {}).get("evidence_linkage")
            for item in report.get("findings", [])
        ]
        evidence_checks = [value == "passed" for value in validation_states]
    passed = sum(assertion["passed"] for assertion in assertions)
    return {
        "scenario_id": scenario_id,
        "run_state": "completed"
        if business_status not in {"FAILED", "CANCELLED", "EXPIRED"}
        else business_status.lower(),
        "model_exposed": False,
        "business_status": business_status,
        "business_outcome_correct": business_status in allowed if allowed else None,
        "numeric_assertions_executed": len(assertions),
        "numeric_assertions_passed": passed,
        "numeric_failed_paths": [
            assertion["path"] for assertion in assertions if not assertion["passed"]
        ],
        "numeric_status": "not_evaluated"
        if not assertions
        else ("pass" if passed == len(assertions) else "fail"),
        "evidence_support": "not_evaluated"
        if not evidence_checks
        else ("pass" if all(evidence_checks) else "fail"),
        "tool_calls": report.get("usage", {}).get("tool_calls"),
        "model_calls": report.get("usage", {}).get("model_calls"),
        "latency_seconds": report.get("usage", {}).get("elapsed_seconds"),
    }


def scenarios_profile_outcomes(root: Path, profile_id: str) -> list[str]:
    profiles = json.loads(
        (root / "examples/evaluation/scenarios.json").read_text(encoding="utf-8")
    )["profiles"]
    profile = profiles[profile_id]
    outcomes = profile.get("allowed_outcomes", [])
    return outcomes if isinstance(outcomes, list) else []


def run_fixed_workflow_baseline(
    root: Path, output_dir: Path, *, stop_after: int | None = None
) -> dict:
    """Run the deterministic workflow over frozen E01–E14 inputs; never invoke a model."""
    root = Path(root)
    output_dir = Path(output_dir)
    scenario_doc = json.loads(
        (root / "examples/evaluation/scenarios.json").read_text(encoding="utf-8")
    )
    requests = json.loads((root / "examples/evaluation/requests.json").read_text(encoding="utf-8"))
    contracts = json.loads(
        (root / "examples/evaluation/contracts.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (root / "examples/evaluation/acceptance_manifest.json").read_text(encoding="utf-8")
    )
    _verify_frozen_manifest(root, manifest)
    scenarios = scenario_doc["scenarios"]
    expected_ids = [f"E{index:02d}" for index in range(1, 15)]
    if [scenario.get("id") for scenario in scenarios] != expected_ids:
        raise BIError("EVALUATION_SPEC_INVALID", "Frozen scenario IDs differ from E01–E14.")
    cases = run_offline_batch(
        scenarios,
        lambda scenario: _fixed_case(root, scenario, requests, contracts, scenario_doc["fixtures"]),
        output_dir / "baseline-checkpoint.json",
        batch_fingerprint=manifest["canonical_sha256"],
        resume=(output_dir / "baseline-checkpoint.json").exists(),
        stop_after=stop_after,
    )
    by_id = {item.get("scenario_id"): item for item in cases["results"]}
    numeric_evaluated = [
        item for item in by_id.values() if item.get("numeric_status") in {"pass", "fail"}
    ]
    numeric_failures = sum(item["numeric_status"] == "fail" for item in numeric_evaluated)
    expected_numeric_cases = len(scenarios) - sum(
        scenario.get("preflight_result") == "blocked" or scenario.get("model_exposed") is False
        for scenario in scenarios
    )
    numeric_status = (
        "not_evaluated"
        if not numeric_evaluated
        else (
            "fail"
            if numeric_failures
            else (
                "pass"
                if len(by_id) == len(scenarios) and len(numeric_evaluated) == expected_numeric_cases
                else "incomplete"
            )
        )
    )
    final_report = {
        "schema_version": "1.0",
        "frozen_manifest_sha256": manifest["canonical_sha256"],
        "scenario_ids": expected_ids,
        "baseline_case_count": len(by_id),
        "batch_status": cases["batch_status"],
        "actual_acceptance_attempts": 0,
        "attempt_denominator": len(scenario_doc["attempts"]),
        "harness_mock_runs": 0,
        "provider_calls": 0,
        "model_calls": 0,
        "agent_choice": {"status": "not_evaluated", "reason": "fixed workflow uses no agent"},
        "numeric_baseline": {
            "cases_evaluated": len(numeric_evaluated),
            "failed_cases": numeric_failures,
            "status": numeric_status,
        },
        "cases": by_id,
    }
    _write_checkpoint(output_dir / "baseline-report.json", final_report)
    return final_report
