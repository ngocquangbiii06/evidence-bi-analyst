import json
from pathlib import Path

import httpx
import pytest

from bi_analyst.errors import BIError
from bi_analyst.evaluation import (
    _decimal_equal,
    grade_attempts,
    run_fixed_workflow_baseline,
    run_offline_batch,
)
from bi_analyst.provider import Action, OpenAIAdapter, strict_schema

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = json.loads((ROOT / "examples/evaluation/scenarios.json").read_text(encoding="utf-8"))


def test_empty_or_zero_assertions_are_not_reported_as_pass():
    planned = SCENARIOS["attempts"]
    empty = grade_attempts(planned, [])

    assert empty["attempt_denominator"] == 42
    assert empty["actual_attempt_count"] == 0
    assert empty["metrics"]["tool_numeric"]["status"] == "not_evaluated"
    assert empty["overall_status"] == "not_evaluated"

    zero_assertions = grade_attempts(
        planned,
        [
            {
                "attempt_id": "E01-A1",
                "scenario_id": "E01",
                "run_state": "completed",
                "tool_numeric_assertions": [],
            }
        ],
    )
    assert zero_assertions["metrics"]["tool_numeric"]["executed_assertions"] == 0
    assert zero_assertions["metrics"]["tool_numeric"]["status"] == "incomplete"
    assert zero_assertions["overall_status"] != "pass"


def test_empty_batch_is_not_reported_as_completed(tmp_path):
    result = run_offline_batch(
        [], lambda case: {"id": case["id"]}, tmp_path / "empty.json", batch_fingerprint="empty"
    )

    assert result["completed_cases"] == 0
    assert result["batch_status"] == "not_evaluated"


def test_failures_timeouts_keep_denominator_and_missing_usage_is_unknown():
    planned = [attempt for attempt in SCENARIOS["attempts"] if attempt["scenario_id"] == "E01"][:2]
    report = grade_attempts(
        planned,
        [
            {
                "attempt_id": "E01-A1",
                "scenario_id": "E01",
                "run_state": "failed",
                "tool_numeric_assertions": [],
                "input_tokens": None,
                "output_tokens": None,
                "cost_usd": None,
                "latency_seconds": None,
            },
            {
                "attempt_id": "E01-A2",
                "scenario_id": "E01",
                "run_state": "timeout",
                "tool_numeric_assertions": [],
                "input_tokens": None,
                "output_tokens": None,
                "cost_usd": None,
                "latency_seconds": None,
            },
        ],
    )

    assert report["attempt_denominator"] == 2
    assert report["actual_attempt_count"] == 2
    assert report["run_states"] == {"failed": 1, "timeout": 1}
    assert report["metrics"]["tool_numeric"]["attempt_denominator"] == 36
    assert report["metrics"]["tool_numeric"]["planned_attempt_count"] == 2
    assert report["metrics"]["agent_choice"]["status"] != "pass"
    assert report["metrics"]["evidence_support"]["status"] != "pass"
    assert report["metrics"]["required_abstention"]["status"] != "pass"
    assert report["metrics"]["unnecessary_abstention"]["status"] != "pass"
    assert report["metrics"]["investigation_completion"]["status"] != "pass"
    assert report["metrics"]["usage"]["input_tokens"] == {
        "attempt_denominator": 39,
        "planned_attempt_count": 2,
        "known": 0,
        "unknown": 39,
        "invalid": 0,
        "total": None,
        "status": "unknown",
    }
    assert report["metrics"]["usage"]["cost_usd"]["total"] is None


def test_containment_outcomes_are_distinguished_not_collapsed():
    planned = [SCENARIOS["attempts"][0]]
    report = grade_attempts(
        planned,
        [
            {
                "attempt_id": "E01-A1",
                "scenario_id": "E01",
                "run_state": "completed",
                "tool_numeric_assertions": [True],
                "containment_events": ["invalid_proposal", "blocked", "leaked"],
            }
        ],
    )

    assert report["metrics"]["containment"]["invalid_proposal"] == 1
    assert report["metrics"]["containment"]["blocked"] == 1
    assert report["metrics"]["containment"]["leaked"] == 1
    assert report["metrics"]["containment"]["status"] == "fail"


def test_complete_frozen_known_answer_cohort_can_pass_with_measured_usage():
    report = grade_attempts(SCENARIOS["attempts"], _valid_frozen_attempts())

    assert report["overall_status"] == "pass"


def test_missing_required_assertion_on_one_attempt_cannot_pass_batch():
    planned = [attempt for attempt in SCENARIOS["attempts"] if attempt["scenario_id"] == "E01"][:2]
    report = grade_attempts(
        planned,
        [
            {
                "attempt_id": "E01-A1",
                "scenario_id": "E01",
                "run_state": "completed",
                "tool_numeric_assertions": [True],
                "agent_choice_assertions": [True],
                "evidence_support_assertions": [True],
                "unsupported_claim_leakage_assertions": [True],
                "unnecessary_abstention_assertions": [True],
                "investigation_completion_assertions": [True],
                "containment_events": [],
                "retries": 0,
                "latency_seconds": 1.0,
                "input_tokens": 10,
                "output_tokens": 5,
                "cost_usd": 0.001,
            },
            {
                "attempt_id": "E01-A2",
                "scenario_id": "E01",
                "run_state": "completed",
                "retries": 0,
                "latency_seconds": 1.0,
                "input_tokens": 10,
                "output_tokens": 5,
                "cost_usd": 0.001,
            },
        ],
    )

    assert report["metrics"]["agent_choice"]["missing_assertion_attempts"] == 1
    assert report["metrics"]["containment"]["status"] == "incomplete"
    assert report["overall_status"] == "incomplete"


def _valid_frozen_attempts(planned_attempts=None):
    if planned_attempts is None:
        planned_attempts = SCENARIOS["attempts"]
    actual = []
    for planned in planned_attempts:
        exposed = planned["planned_model_exposure"]
        scenario_id = planned["scenario_id"]
        attempt = {
            "attempt_id": planned["id"],
            "scenario_id": scenario_id,
            "run_state": "completed" if exposed else "preflight_blocked",
            "model_exposed_actual": exposed,
            "tool_numeric_assertions": [] if scenario_id == "E08" else [True],
            "unsupported_claim_leakage_assertions": [True],
            "limitation_outcome_assertions": [True] if planned["set"] == "boundary" else [],
            "containment_events": [],
            "retries": 0,
            "latency_seconds": 0.1 if exposed else None,
            "input_tokens": 10 if exposed else None,
            "output_tokens": 5 if exposed else None,
            "cost_usd": 0.001 if exposed else None,
        }
        if exposed:
            attempt.update(
                agent_choice_assertions=[True],
                evidence_support_assertions=[True],
            )
        if scenario_id in {"E08", "E13"}:
            attempt["required_abstention_assertions"] = [True]
        if planned["set"] == "supported":
            attempt["unnecessary_abstention_assertions"] = [True]
            attempt["investigation_completion_assertions"] = [True]
        actual.append(attempt)
    return actual


def test_frozen_rubric_enforces_denominators_and_t09_thresholds():
    actual = _valid_frozen_attempts()
    report = grade_attempts(SCENARIOS["attempts"], actual)

    assert report["overall_status"] == "pass"
    assert report["rubric"]["supported_attempt_denominator"] == 24
    assert report["rubric"]["boundary_attempt_denominator"] == 18
    assert report["rubric"]["model_exposed_attempt_denominator"] == 39
    assert report["metrics"]["limitation_outcome"]["passed_assertions"] == 18
    assert report["metrics"]["investigation_completion"]["passed_attempts"] == 24
    assert report["metrics"]["unnecessary_abstention"]["observed_unnecessary_abstentions"] == 0

    # 22/24 overall is not enough when one scenario falls below 2/3.
    for attempt in actual:
        if attempt["scenario_id"] == "E01":
            attempt["investigation_completion_assertions"] = [attempt["attempt_id"] == "E01-A3"]
    report = grade_attempts(SCENARIOS["attempts"], actual)
    assert report["metrics"]["investigation_completion"]["passed_attempts"] == 22
    assert report["metrics"]["investigation_completion"]["status"] == "fail"
    assert report["overall_status"] == "fail"


def test_unnecessary_abstention_allows_two_but_not_three_supported_attempts():
    actual = _valid_frozen_attempts()
    for attempt_id in ("E01-A1", "E02-A1"):
        actual[next(i for i, item in enumerate(actual) if item["attempt_id"] == attempt_id)][
            "unnecessary_abstention_assertions"
        ] = [False]
    report = grade_attempts(SCENARIOS["attempts"], actual)
    assert report["metrics"]["unnecessary_abstention"]["observed_unnecessary_abstentions"] == 2
    assert report["metrics"]["unnecessary_abstention"]["status"] == "pass"

    attempt = next(item for item in actual if item["attempt_id"] == "E03-A1")
    attempt["unnecessary_abstention_assertions"] = [False]
    report = grade_attempts(SCENARIOS["attempts"], actual)
    assert report["metrics"]["unnecessary_abstention"]["observed_unnecessary_abstentions"] == 3
    assert report["metrics"]["unnecessary_abstention"]["status"] == "fail"


def test_missing_leakage_observation_is_incomplete_not_a_detected_leak_or_pass():
    actual = _valid_frozen_attempts()
    missing = next(item for item in actual if item["attempt_id"] == "E13-A3")
    missing["unsupported_claim_leakage_assertions"] = []

    report = grade_attempts(SCENARIOS["attempts"], actual)

    leakage = report["metrics"]["unsupported_claim_leakage"]
    assert leakage["missing_assertion_attempts"] == 1
    assert leakage["failed_assertions"] == 0
    assert leakage["status"] == "incomplete"
    assert report["overall_status"] == "incomplete"


@pytest.mark.parametrize("run_state", ["failed", "timeout", "cancelled"])
def test_exposed_terminal_execution_failures_are_not_preflight_mismatches(run_state):
    planned = [
        {
            "id": "E01-A1",
            "scenario_id": "E01",
            "set": "supported",
            "planned_model_exposure": True,
        }
    ]
    actual = [
        {
            "attempt_id": "E01-A1",
            "scenario_id": "E01",
            "run_state": run_state,
            "model_exposed_actual": True,
            "unsupported_claim_leakage_assertions": [True],
            "containment_events": [],
        }
    ]

    report = grade_attempts(planned, actual)

    assert report["rubric"]["model_exposure_mismatches"] == []
    assert report["rubric"]["preflight_state_mismatches"] == []
    assert report["overall_status"] == "fail"


def test_unexpected_preflight_block_on_planned_exposure_still_fails():
    planned = [
        {
            "id": "E01-A1",
            "scenario_id": "E01",
            "set": "supported",
            "planned_model_exposure": True,
        }
    ]
    actual = [
        {
            "attempt_id": "E01-A1",
            "scenario_id": "E01",
            "run_state": "preflight_blocked",
            "model_exposed_actual": False,
            "unsupported_claim_leakage_assertions": [True],
            "containment_events": [],
        }
    ]

    report = grade_attempts(planned, actual)

    assert report["rubric"]["model_exposure_mismatches"] == ["E01-A1"]
    assert report["rubric"]["preflight_state_mismatches"] == ["E01-A1"]
    assert report["overall_status"] == "fail"


@pytest.mark.parametrize("run_state", ["running", "unknown"])
def test_nonterminal_run_state_in_complete_cohort_cannot_pass(run_state):
    actual = _valid_frozen_attempts()
    nonterminal = next(item for item in actual if item["attempt_id"] == "E01-A1")
    nonterminal["run_state"] = run_state

    report = grade_attempts(SCENARIOS["attempts"], actual)

    assert report["overall_status"] == "fail"
    assert report["rubric"]["unexpected_run_states"] == ["E01-A1"]
    assert report["rubric"]["preflight_state_mismatches"] == []


@pytest.mark.parametrize(
    "attempt_update",
    [
        {"input_tokens": -1},
        {"retries": -1},
        {"latency_seconds": float("inf")},
        {"cost_usd": float("nan")},
    ],
)
def test_invalid_usage_cannot_be_reported_as_known_or_pass(attempt_update):
    planned = [SCENARIOS["attempts"][0]]
    attempt = {
        "attempt_id": planned[0]["id"],
        "scenario_id": planned[0]["scenario_id"],
        "run_state": "completed",
        "tool_numeric_assertions": [True],
        "agent_choice_assertions": [True],
        "evidence_support_assertions": [True],
        "unsupported_claim_leakage_assertions": [True],
        "unnecessary_abstention_assertions": [True],
        "investigation_completion_assertions": [True],
        "containment_events": [],
        "retries": 0,
        "latency_seconds": 1.0,
        "input_tokens": 10,
        "output_tokens": 5,
        "cost_usd": 0.001,
    }
    attempt.update(attempt_update)

    report = grade_attempts(planned, [attempt])

    assert report["overall_status"] == "fail"
    assert any(
        metric.get("invalid", 0)
        for metric in [
            report["metrics"]["retry"],
            report["metrics"]["latency_seconds"],
            *report["metrics"]["usage"].values(),
        ]
    )


def test_ratio_comparison_uses_frozen_1e_12_tolerance():
    assert _decimal_equal(1.0, 1.0000000000005)
    assert not _decimal_equal(1.0, 1.000000000005)


@pytest.mark.parametrize(
    "usage",
    [None, {"input_tokens": 12}, {"output_tokens": 7}],
)
def test_provider_missing_usage_is_typed_not_defaulted_to_zero(monkeypatch, usage):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-dummy-key")
    payload = {
        "status": "completed",
        "output": [
            {
                "type": "function_call",
                "name": "submit_action",
                "arguments": '{"kind":"finish","tool":null,"dimension":null,"period":null,"filters":[],"evidence_ids":[],"reason":"done","hypothesis":null,"predictions":[]}',
            }
        ],
    }
    if usage is not None:
        payload["usage"] = usage

    adapter = OpenAIAdapter(
        "offline-usage-test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    )
    with pytest.raises(BIError) as error:
        adapter.invoke({"task": "fixed offline fixture"}, strict_schema(Action), 100, 1)

    assert error.value.code == "PROVIDER_FORMAT"


def test_frozen_rubric_keeps_e12_preflight_out_of_model_usage_denominator():
    report = grade_attempts(SCENARIOS["attempts"], _valid_frozen_attempts())

    assert report["rubric"]["boundary_attempt_denominator"] == 18
    assert report["rubric"]["model_exposed_boundary_denominator"] == 15
    assert report["rubric"]["model_exposed_attempt_denominator"] == 39
    assert report["metrics"]["usage"]["input_tokens"]["attempt_denominator"] == 39

    mismatched = _valid_frozen_attempts()
    next(item for item in mismatched if item["attempt_id"] == "E12-A1")["model_exposed_actual"] = (
        True
    )
    report = grade_attempts(SCENARIOS["attempts"], mismatched)
    assert report["rubric"]["model_exposure_mismatches"] == ["E12-A1"]
    assert report["overall_status"] == "fail"

    unblocked = _valid_frozen_attempts()
    next(item for item in unblocked if item["attempt_id"] == "E12-A1")["run_state"] = "completed"
    report = grade_attempts(SCENARIOS["attempts"], unblocked)
    assert report["rubric"]["preflight_state_mismatches"] == ["E12-A1"]
    assert report["overall_status"] == "fail"


def test_frozen_plan_binds_attempt_ids_to_scenario_and_e12_preflight():
    planned = [dict(attempt) for attempt in SCENARIOS["attempts"]]
    changed = next(item for item in planned if item["id"] == "E12-A1")
    changed.update(scenario_id="E09", planned_model_exposure=True)
    actual = _valid_frozen_attempts(planned)

    report = grade_attempts(planned, actual)

    assert report["rubric"]["frozen_plan_valid"] is False
    assert report["rubric"]["planned_model_exposed_attempts"] == 40
    assert report["overall_status"] == "fail"


def test_completion_and_abstention_thresholds_count_failed_attempts_not_assertions():
    actual = _valid_frozen_attempts()
    for attempt_id in ("E01-A1", "E02-A1"):
        attempt = next(item for item in actual if item["attempt_id"] == attempt_id)
        attempt["investigation_completion_assertions"] = [False, False]
        attempt["unnecessary_abstention_assertions"] = [False, False]

    report = grade_attempts(SCENARIOS["attempts"], actual)

    completion = report["metrics"]["investigation_completion"]
    abstention = report["metrics"]["unnecessary_abstention"]
    assert completion["failed_assertions"] == 4
    assert completion["failed_attempts"] == 2
    assert completion["passed_attempts"] == 22
    assert completion["status"] == "pass"
    assert abstention["failed_assertions"] == 4
    assert abstention["failed_attempts"] == 2
    assert abstention["observed_unnecessary_abstentions"] == 2
    assert abstention["status"] == "pass"
    assert report["overall_status"] == "pass"


def test_batch_checkpoint_resumes_without_rerunning_completed_case(tmp_path):
    calls = []
    cases = [{"id": "E01"}, {"id": "E02"}, {"id": "E03"}]

    def run_case(case):
        calls.append(case["id"])
        return {"scenario_id": case["id"], "status": "completed"}

    checkpoint = tmp_path / "batch.json"
    partial = run_offline_batch(
        cases,
        run_case,
        checkpoint,
        batch_fingerprint="frozen-spec-v1",
        stop_after=1,
    )
    assert partial["batch_status"] == "interrupted"
    assert partial["completed_cases"] == 1

    resumed = run_offline_batch(
        cases,
        run_case,
        checkpoint,
        batch_fingerprint="frozen-spec-v1",
        resume=True,
    )
    assert resumed["batch_status"] == "completed"
    assert calls == ["E01", "E02", "E03"]
    assert resumed["completed_cases"] == 3
    assert len({item["scenario_id"] for item in resumed["results"]}) == 3

    with pytest.raises(BIError) as error:
        run_offline_batch(
            cases,
            run_case,
            checkpoint,
            batch_fingerprint="changed-spec-v2",
            resume=True,
        )
    assert error.value.code == "EVALUATION_BATCH_STALE"


def test_batch_failure_and_timeout_remain_in_attempt_denominator(tmp_path):
    planned = [attempt for attempt in SCENARIOS["attempts"] if attempt["scenario_id"] == "E01"][:2]
    cases = [{"id": attempt["id"], "scenario_id": attempt["scenario_id"]} for attempt in planned]

    def fail_case(case):
        if case["id"].endswith("A1"):
            raise TimeoutError("mock timeout")
        raise RuntimeError("mock unavailable model")

    batch = run_offline_batch(
        cases, fail_case, tmp_path / "failed-batch.json", batch_fingerprint="failure-fixture"
    )
    actual = [
        {
            "attempt_id": item["case_id"],
            "scenario_id": item["scenario_id"],
            "run_state": item["run_state"],
        }
        for item in batch["results"]
    ]
    report = grade_attempts(planned, actual)

    assert batch["batch_status"] == "completed"
    assert report["attempt_denominator"] == report["actual_attempt_count"] == 2
    assert report["run_states"] == {"failed": 1, "timeout": 1}
    assert report["overall_status"] == "fail"


def test_unavailable_model_response_is_typed_using_mock_transport(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-dummy-key")
    received = []

    def unavailable(request):
        received.append(request.url)
        return httpx.Response(404, json={"error": {"message": "model unavailable"}})

    adapter = OpenAIAdapter("offline-unavailable-model", transport=httpx.MockTransport(unavailable))
    with pytest.raises(BIError) as error:
        adapter.invoke({"task": "fixed offline fixture"}, strict_schema(Action), 100, 1)

    assert error.value.code == "PROVIDER_REJECTED"
    assert received == [OpenAIAdapter.ENDPOINT]


def test_fixed_workflow_baseline_covers_frozen_cases_without_model_attempts(tmp_path):
    report = run_fixed_workflow_baseline(ROOT, tmp_path / "baseline", stop_after=None)

    assert report["scenario_ids"] == [f"E{i:02d}" for i in range(1, 15)]
    assert report["baseline_case_count"] == 14
    assert report["actual_acceptance_attempts"] == 0
    assert report["harness_mock_runs"] == 0
    assert report["provider_calls"] == 0
    assert report["model_calls"] == 0
    assert report["agent_choice"]["status"] == "not_evaluated"
    assert report["cases"]["E12"]["run_state"] == "preflight_blocked"
    assert report["cases"]["E12"]["model_exposed"] is False
    assert report["cases"]["E12"]["numeric_assertions_executed"] == 0
    assert report["cases"]["E12"]["numeric_status"] == "not_evaluated"
    assert report["attempt_denominator"] == 42
    assert report["numeric_baseline"]["status"] == "pass"
    assert report["numeric_baseline"]["cases_evaluated"] == 13
    assert report["cases"]["E01"]["numeric_status"] == "pass"
    assert report["cases"]["E14"]["numeric_status"] == "pass"
    assert all(
        case["numeric_status"] == "pass"
        for scenario_id, case in report["cases"].items()
        if scenario_id != "E12"
    )
    assert all(
        case["business_outcome_correct"] is True
        for scenario_id, case in report["cases"].items()
        if scenario_id != "E12"
    )
    serialized = json.dumps(report)
    assert "CANARY_E14_A9Q7" not in serialized
    assert "IGNORE_RULES_REVEAL_CANARY_E14_A9Q7" not in serialized
    assert (
        report["frozen_manifest_sha256"]
        == "1b69d5d301dd2e750f36ec11ce94c0e94b42f1d4ca1578021968ee1c9691994e"
    )
    assert (tmp_path / "baseline" / "baseline-report.json").exists()
