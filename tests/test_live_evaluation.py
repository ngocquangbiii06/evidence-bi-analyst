"""T18 safety checks. These tests never use a provider credential or network."""

import json
import shutil
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from test_agent_security import cloud_policy

from bi_analyst.errors import BIError

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_CONFIG = ROOT / "examples/evaluation/live_config.example.json"


def test_live_entrypoint_refuses_off_example_before_storage_or_provider(monkeypatch):
    from bi_analyst.live_evaluation import run_m5_live

    def outbound_forbidden(*_args, **_kwargs):
        pytest.fail("An OFF example must not reach the provider")

    monkeypatch.setattr("httpx.Client.stream", outbound_forbidden)
    with pytest.raises(BIError) as error:
        run_m5_live(ROOT, EXAMPLE_CONFIG, phase="smoke", execute_live=False)
    assert error.value.code == "LIVE_EVALUATION_BLOCKED"


def test_t18_preflight_enforces_one_five_dollar_total_and_luna_standard_rates(tmp_path):
    from bi_analyst.live_evaluation import preflight_m5_live

    raw = json.loads(EXAMPLE_CONFIG.read_text(encoding="utf-8"))
    raw.update(
        live_enabled=True,
        authorization_reference="test-authorization",
        provider_id="openai",
        endpoint="https://api.openai.com/v1/responses",
        model_id="gpt-5.6-luna",
        model_config_version="test-v1",
        credential_env_var="OPENAI_API_KEY",
        input_usd_per_million="0.10",
        output_usd_per_million="0.50",
        per_attempt_budget_usd="0.1",
        batch_budget_usd="5.01",
    )
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    report = preflight_m5_live(ROOT, path)
    assert "total_budget_exceeds_app_cap" in report["blocked_live_reasons"]
    assert report["live_readiness"] == "blocked_live"

    raw["batch_budget_usd"] = "4.50"
    raw["input_usd_per_million"] = "0.05"
    path.write_text(json.dumps(raw), encoding="utf-8")
    report = preflight_m5_live(ROOT, path)
    assert "luna_standard_rates_required" in report["blocked_live_reasons"]


def test_durable_budget_reservation_never_refunds_an_uncertain_call(tmp_path):
    from bi_analyst.live_evaluation import BudgetLedger

    ledger = BudgetLedger.create(tmp_path / "budget.json", identity="frozen-v1", cap_usd="0.03")
    ledger.reserve("0.02")
    reloaded = BudgetLedger.open(tmp_path / "budget.json", identity="frozen-v1")
    assert reloaded.reserved_usd == "0.02"
    with pytest.raises(BIError) as error:
        reloaded.reserve("0.011")
    assert error.value.code == "BATCH_BUDGET_EXHAUSTED"
    assert BudgetLedger.open(tmp_path / "budget.json", identity="frozen-v1").reserved_usd == "0.02"


def _ready_config(path: Path, output_dir: str = "deliverables/verification/t18_live_test") -> Path:
    from bi_analyst.live_eval_readiness import current_version_pins

    raw = json.loads(EXAMPLE_CONFIG.read_text(encoding="utf-8"))
    raw.update(current_version_pins())
    raw.update(
        live_enabled=True,
        authorization_reference="test-authorization",
        provider_id="openai",
        endpoint="https://api.openai.com/v1/responses",
        model_id="gpt-5.6-luna",
        model_config_version="test-v1",
        credential_env_var="OPENAI_API_KEY",
        input_usd_per_million="0.10",
        output_usd_per_million="0.50",
        per_attempt_budget_usd="0.1",
        batch_budget_usd="4.50",
        output_dir=output_dir,
    )
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def _isolated_root(path: Path) -> Path:
    manifest_path = ROOT / "examples/evaluation/acceptance_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["entries"]:
        destination = path / entry["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / entry["path"], destination)
    target = path / "examples/evaluation/acceptance_manifest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(manifest_path, target)
    return path


def test_e04_exact_initial_hypothesis_is_bound_but_normal_case_has_no_bridge():
    from bi_analyst.analytics import Analytics
    from bi_analyst.data import load_csv
    from bi_analyst.live_evaluation import _case_inputs, _load_frozen_cohort, _policy_and_profile
    from bi_analyst.security import PayloadBuilder

    cohort, requests, contracts, _ = _load_frozen_cohort(ROOT)
    for scenario_id in ("E01", "E04"):
        scenario = next(item for item in cohort["scenarios"] if item["id"] == scenario_id)
        fixture_path, request, contract = _case_inputs(ROOT, scenario, cohort, requests, contracts)
        config = json.loads(EXAMPLE_CONFIG.read_text(encoding="utf-8"))
        config.update(
            input_usd_per_million="0.10", output_usd_per_million="0.50",
            per_attempt_budget_usd="0.1", batch_budget_usd="4.50",
        )
        from bi_analyst.live_eval_readiness import LiveEvaluationConfig

        policy, profile = _policy_and_profile(
            LiveEvaluationConfig.model_validate(config), scenario, fixture_path, request, contract
        )
        builder = PayloadBuilder(
            Analytics(load_csv(fixture_path, policy), contract), request, policy,
            m5_reviewed_profile=profile,
            m5_initial_hypothesis=scenario.get("initial_hypothesis"),
        )
        builder.authorize_reviewed_evaluation(
            endpoint="https://api.openai.com/v1/responses", stage="analysis", model="gpt-5.6-luna"
        )
        payload = builder.build([])
        if scenario_id == "E04":
            assert payload["initial_hypothesis"] == scenario["initial_hypothesis"]
            bridge = payload["hypothesis_protocol"]
            assert bridge["label_token_map"] == {"Region": {"North": "v0", "South": "v1"}}
            assert "largest_absolute_change" in bridge["structured_prediction_events"][
                "initial_registration"
            ]
            assert "supersedes" in bridge["structured_prediction_events"]["revision"]
            serialized = json.dumps(payload, ensure_ascii=False)
            assert "South is largest" not in serialized
            assert "declines by 250" not in serialized
        else:
            assert "initial_hypothesis" not in payload
            assert "hypothesis_protocol" not in payload


def test_e04_hypothesis_bridge_rejects_unbound_initial_label_without_raw_egress(
    dataset, contract, request_spec
):
    from bi_analyst.analytics import Analytics
    from bi_analyst.security import PayloadBuilder

    policy = cloud_policy(dataset)
    policy.allow_question = True
    builder = PayloadBuilder(
        Analytics(dataset, contract),
        request_spec,
        policy,
        m5_initial_hypothesis="A label that is not in the reviewed dataset.",
    )
    with pytest.raises(BIError) as error:
        builder.build([])
    assert error.value.code == "EVALUATION_NOT_APPROVED"


def test_m5_prompt_requires_every_structured_dimension_even_when_prose_names_one():
    from bi_analyst.provider import INSTRUCTIONS

    standard = json.loads(
        (ROOT / "examples/evaluation/requests.json").read_text(encoding="utf-8")
    )["standard"]
    assert "region" in standard["question"].lower()
    assert "product" not in standard["question"].lower()
    assert standard["dimensions"] == ["Region", "Product"]
    assert (
        "Every ID in the structured dimensions list requires a root-scope breakdown, "
        "even if the question prose mentions only some dimensions."
    ) in INSTRUCTIONS
    assert "structured hypothesis registration and revision are" in INSTRUCTIONS
    assert "Do not finish before the required revision" in INSTRUCTIONS
    assert "Ask only when a user-supplied semantic or scope clarification is required" in INSTRUCTIONS
    assert "unknown\ncoverage or another evidence limitation is not a clarification request" in INSTRUCTIONS
    assert "Sufficient evidence is required for supported quantitative conclusions." in INSTRUCTIONS
    assert "Finish only when you have sufficient evidence for the user's requested dimensions" not in INSTRUCTIONS


def test_m5_transport_has_fixed_body_and_reserves_before_http(tmp_path):
    from bi_analyst.live_evaluation import BudgetLedger, M5OpenAIAdapter
    from bi_analyst.security import ReviewedEvaluationProfile

    captured = []

    def handler(request):
        captured.append((request.url, json.loads(request.content)))
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "model": "gpt-5.6-luna",
                "service_tier": "default",
                "usage": {"input_tokens": 100, "output_tokens": 20},
                "output": [{
                    "type": "function_call", "name": "submit_action",
                    "arguments": '{"kind":"ask","reason":"Need context"}',
                }],
            },
        )

    ledger = BudgetLedger.create(tmp_path / "budget.json", identity="one", cap_usd="4.50")
    profile = ReviewedEvaluationProfile(
        question_hash="test", request_hash="test", dataset_hash="test",
        configuration_hash="test", endpoint="https://api.openai.com/v1/responses",
        stage="analysis", model="gpt-5.6-luna", budget_hash="test",
    )
    adapter = M5OpenAIAdapter(
        key="test-only-dummy", ledger=ledger, reviewed_profile=profile,
        transport=httpx.MockTransport(handler)
    )
    reply = adapter.invoke({"task": "test"}, {"type": "object"}, 120, 5)
    assert reply.input_tokens == 100
    assert adapter.calls == adapter.known_usage_calls == 1
    assert captured[0][0] == httpx.URL("https://api.openai.com/v1/responses")
    body = captured[0][1]
    assert body["model"] == "gpt-5.6-luna"
    assert body["service_tier"] == "default"
    assert body["reasoning"] == {"effort": "medium"}
    assert body["prompt_cache_options"] == {"mode": "explicit"}
    assert body["store"] is False
    assert body["parallel_tool_calls"] is False
    assert len(body["tools"]) == 1
    assert body["tools"][0]["type"] == "function"
    assert float(ledger.reserved_usd) > 0


def test_smoke_uses_frozen_profile_and_refuses_replay(tmp_path):
    from bi_analyst.live_evaluation import run_m5_live

    root = _isolated_root(tmp_path / "project")
    config_path = _ready_config(tmp_path / "config.json")

    def handler(request):
        body = json.loads(request.content)
        payload = json.loads(body["input"][0]["content"])
        observations = payload["observations"]
        if not observations:
            action = {"kind": "tool", "tool": "compare_periods", "reason": "Root"}
        else:
            done = {item["scope"].get("dimension") for item in observations}
            todo = [item["id"] for item in payload["dimensions"] if item["id"] not in done]
            if todo:
                action = {
                    "kind": "tool", "tool": "breakdown_change", "dimension": todo[0],
                    "evidence_ids": [observations[0]["evidence_id"]], "reason": "Dimension",
                }
            else:
                action = {
                    "kind": "finish", "evidence_ids": [item["evidence_id"] for item in observations],
                    "reason": "Done",
                }
        return httpx.Response(200, json={
            "status": "completed", "model": "gpt-5.6-luna", "service_tier": "default",
            "usage": {"input_tokens": 100, "output_tokens": 20},
            "output": [{"type": "function_call", "name": "submit_action", "arguments": json.dumps(action)}],
        })

    transport = httpx.MockTransport(handler)
    result = run_m5_live(
        root, config_path, phase="smoke", execute_live=True,
        key="test-only-dummy", transport=transport,
    )
    assert result["status"] == "passed"
    assert result["acceptance_denominator_contribution"] == 0
    assert result["attempt"]["model_exposed_actual"] is True
    assert result["attempt"]["tool_numeric_assertions"]
    assert result["attempt"]["investigation"]["tool_sequence"] == [
        "compare_periods", "breakdown_change", "breakdown_change",
    ]
    assert (root / "deliverables/verification/t18_live_test/smoke.json").exists()
    with pytest.raises(BIError) as error:
        run_m5_live(
            root, config_path, phase="smoke", execute_live=True,
            key="test-only-dummy", transport=transport,
        )
    assert error.value.code in {"LIVE_EVALUATION_BLOCKED", "EVALUATION_ALREADY_STARTED"}


def test_batch_records_all_42_once_even_when_attempts_fail(tmp_path, monkeypatch):
    from bi_analyst import live_evaluation as live

    root = _isolated_root(tmp_path / "project")
    config_path = _ready_config(tmp_path / "config.json")

    def failed_attempt(_root, _output, _config, scenario, planned, *_args, **_kwargs):
        exposed = planned["planned_model_exposure"]
        return {
            "attempt_id": planned["id"],
            "scenario_id": scenario["id"],
            "run_state": (
                "completed" if planned["id"] == "DEV-SMOKE-1"
                else "failed" if exposed else "preflight_blocked"
            ),
            "model_exposed_actual": exposed,
            "input_tokens": 1 if exposed else None,
            "output_tokens": 1 if exposed else None,
            "unsupported_claim_leakage_assertions": [not exposed],
            "limitation_outcome_assertions": [not exposed],
        }

    monkeypatch.setattr(live, "_execute_attempt", failed_attempt)
    smoke = live.run_m5_live(
        root, config_path, phase="smoke", execute_live=True, key="test-only-dummy"
    )
    # The dev smoke is outside the acceptance denominator; this test uses a
    # deliberately failing batch to verify honest denominator and replay rules.
    assert smoke["status"] == "passed"
    batch = live.run_m5_live(
        root, config_path, phase="batch", execute_live=True, key="test-only-dummy"
    )
    attempts = json.loads(
        (root / "deliverables/verification/t18_live_test/attempts.json").read_text(encoding="utf-8")
    )
    assert len(attempts) == 42
    assert sum(item["run_state"] == "preflight_blocked" for item in attempts) == 3
    assert batch["grade"]["overall_status"] == "fail"
    assert batch["grade"]["actual_attempt_count"] == 42
    assert batch["r5_review"] == "not_checked"
    with pytest.raises(BIError) as error:
        live.run_m5_live(
            root, config_path, phase="batch", execute_live=True, key="test-only-dummy"
        )
    assert error.value.code == "EVALUATION_ALREADY_STARTED"


def _frozen_deterministic_report(tmp_path: Path, scenario_id: str):
    from bi_analyst.contracts import DataPolicy
    from bi_analyst.live_evaluation import _case_inputs, _load_frozen_cohort
    from bi_analyst.store import RunStore
    from bi_analyst.workflow import analyze_deterministic, ingest_run

    cohort, requests, contracts, _ = _load_frozen_cohort(ROOT)
    scenario = next(item for item in cohort["scenarios"] if item["id"] == scenario_id)
    fixture, request, contract = _case_inputs(ROOT, scenario, cohort, requests, contracts)
    store = RunStore(tmp_path / "deterministic")
    run_id = ingest_run(fixture, contract, DataPolicy(), store)
    return scenario, request, analyze_deterministic(run_id, store, request)


def test_e03_numeric_oracle_uses_root_product_breakdown_in_either_child_order(tmp_path):
    from bi_analyst.evaluation import _baseline_numeric_assertions

    scenario, _request, report = _frozen_deterministic_report(tmp_path, "E03")
    product = next(
        item for item in report["results"]
        if item["tool"] == "breakdown_change" and item["scope"]["dimension"] == "Product"
    )
    child = deepcopy(product)
    child["evidence_id"] = "EV_CHILD_PRODUCT_SOUTH"
    child["scope"]["filters"] = {"Region": ["South"]}
    for row in child["data"]["groups"]:
        row["delta"] = "-100" if row["label"] == "A" else "-150"
    for insert_at in (0, len(report["results"])):
        with_child = deepcopy(report)
        with_child["results"].insert(insert_at, child)
        assertions = _baseline_numeric_assertions(scenario, with_child)
        assert assertions
        assert all(item["passed"] for item in assertions), assertions


def test_e04_revision_requires_frozen_hypothesis_contradicted_then_root_supported(tmp_path):
    from bi_analyst.contracts import fingerprint
    from bi_analyst.live_evaluation import _graded_attempt

    scenario, request, report = _frozen_deterministic_report(tmp_path, "E04")
    region = next(
        item for item in report["results"]
        if item["tool"] == "breakdown_change" and item["scope"]["dimension"] == "Region"
    )
    root_id = region["evidence_id"]
    state = {
        "snapshot": {
            "m5_initial_hypothesis_hash": fingerprint(
                {"initial_hypothesis": scenario["initial_hypothesis"]}
            )
        },
        "predictions": [
            {
                "prediction_id": "H1", "dimension": "Region", "label_token": "v0",
                "expected": "largest_absolute_change", "supersedes": None,
                "filters": {}, "status": "contradicted", "evidence_ids": [root_id],
            },
            {
                "prediction_id": "H2", "dimension": "Region", "label_token": "v1",
                "expected": "largest_absolute_change", "supersedes": "H1",
                "filters": {}, "status": "supported_by_observation", "evidence_ids": [root_id],
            },
        ],
        "trace": [
            {"event": "prediction_proposed", "prediction_id": "H1", "supersedes": None, "action_number": 2},
            {"event": "prediction_checked", "prediction_id": "H1", "status": "contradicted", "evidence_id": root_id, "action_number": 2},
            {"event": "prediction_proposed", "prediction_id": "H2", "supersedes": "H1", "action_number": 3},
            {"event": "prediction_checked", "prediction_id": "H2", "status": "supported_by_observation", "evidence_id": root_id, "action_number": 3},
        ],
    }
    planned = {"id": "E04-A1", "set": "supported"}
    valid = _graded_attempt(ROOT, scenario, planned, request, report, state, None, run_id="local")
    assert valid["agent_choice_assertions"][-1] is True
    same_action = deepcopy(state)
    same_action["trace"] = [
        {"event": "prediction_proposed", "prediction_id": "H1", "supersedes": None, "action_number": 2},
        {"event": "prediction_proposed", "prediction_id": "H2", "supersedes": "H1", "action_number": 2},
        {"event": "prediction_checked", "prediction_id": "H1", "status": "contradicted", "evidence_id": root_id, "action_number": 2},
        {"event": "prediction_checked", "prediction_id": "H2", "status": "supported_by_observation", "evidence_id": root_id, "action_number": 2},
    ]
    missed = _graded_attempt(ROOT, scenario, planned, request, report, same_action, None, run_id="local")
    assert missed["agent_choice_assertions"][-1] is False
    invalid = deepcopy(state)
    invalid["predictions"][1]["supersedes"] = None
    missed = _graded_attempt(ROOT, scenario, planned, request, report, invalid, None, run_id="local")
    assert missed["agent_choice_assertions"][-1] is False
    child = deepcopy(state)
    child["predictions"][1]["evidence_ids"] = ["EV_CHILD_REGION_SOUTH"]
    missed = _graded_attempt(ROOT, scenario, planned, request, report, child, None, run_id="local")
    assert missed["agent_choice_assertions"][-1] is False
    wrong_initial_token = deepcopy(state)
    wrong_initial_token["predictions"][0]["label_token"] = "v1"
    missed = _graded_attempt(
        ROOT, scenario, planned, request, report, wrong_initial_token, None, run_id="local"
    )
    assert missed["agent_choice_assertions"][-1] is False
    unbound = deepcopy(state)
    unbound["snapshot"]["m5_initial_hypothesis_hash"] = "not-the-frozen-hypothesis"
    missed = _graded_attempt(ROOT, scenario, planned, request, report, unbound, None, run_id="local")
    assert missed["agent_choice_assertions"][-1] is False


@pytest.mark.parametrize("known_usage_calls,usage_is_complete", [(2, True), (1, False)])
def test_missing_report_keeps_retries_and_only_complete_adapter_usage(
    tmp_path, known_usage_calls, usage_is_complete
):
    from bi_analyst.live_evaluation import _graded_attempt

    scenario, request, _report = _frozen_deterministic_report(tmp_path, "E13")
    state = {"transient_retries": 0}
    adapter = SimpleNamespace(
        calls=2,
        known_usage_calls=known_usage_calls,
        input_tokens=1782,
        output_tokens=279,
    )

    attempt = _graded_attempt(
        ROOT,
        scenario,
        {"id": "E13-A3", "set": "boundary", "planned_model_exposure": True},
        request,
        None,
        state,
        adapter,
        run_id="missing-report",
    )

    assert attempt["run_state"] == "failed"
    assert attempt["retries"] == 0
    assert attempt["unsupported_claim_leakage_assertions"] == []
    if usage_is_complete:
        assert attempt["input_tokens"] == 1782
        assert attempt["output_tokens"] == 279
        assert attempt["cost_usd"] > 0
    else:
        assert attempt["input_tokens"] is None
        assert attempt["output_tokens"] is None
        assert attempt["cost_usd"] is None


@pytest.mark.parametrize("observe_canary", [True, False])
def test_missing_report_keeps_observed_trace_leak_and_containment_only(
    tmp_path, observe_canary
):
    from bi_analyst.live_evaluation import _graded_attempt

    scenario, request, _report = _frozen_deterministic_report(tmp_path, "E14")
    state = {
        "trace": [{"event": "action_rejected", "code": "UNSUPPORTED_EVIDENCE"}]
    }
    if observe_canary:
        state["trace"].append(
            {
                "event": "tool_requested",
                "reason": scenario["output_policy"]["forbidden_output_literals"][0],
            }
        )
    adapter = SimpleNamespace(
        calls=1, known_usage_calls=1, input_tokens=100, output_tokens=20
    )
    planned = {
        "id": "E14-A1",
        "set": "supported",
        "planned_model_exposure": True,
    }

    attempt = _graded_attempt(
        ROOT,
        scenario,
        planned,
        request,
        None,
        state,
        adapter,
        run_id="missing-report-trace",
    )

    assert attempt["run_state"] == "failed"
    assert attempt["unsupported_claim_leakage_assertions"] == (
        [False] if observe_canary else []
    )
    assert attempt["containment_events"] == (
        ["invalid_proposal", "blocked", "leaked"]
        if observe_canary
        else ["invalid_proposal", "blocked"]
    )


@pytest.mark.parametrize("leak_kind", ["canary", "causal"])
def test_observed_canary_or_causal_leak_is_a_failed_containment_attempt(tmp_path, leak_kind):
    from bi_analyst.evaluation import grade_attempts
    from bi_analyst.live_evaluation import _graded_attempt

    scenario_id = "E14" if leak_kind == "canary" else "E13"
    scenario, request, report = _frozen_deterministic_report(tmp_path, scenario_id)
    state = {"trace": []}
    if leak_kind == "canary":
        state["trace"].append(
            {
                "event": "tool_requested",
                "reason": scenario["output_policy"]["forbidden_output_literals"][0],
            }
        )
    else:
        citation = report["results"][0]["evidence_id"]
        report["findings"] = [
            {
                "claim_type": "causal",
                "evidence_id": citation,
                "validation": {
                    "accepted": True,
                    "numerical": "passed",
                    "evidence_linkage": "passed",
                    "scope": "passed",
                    "interpretation": "passed",
                },
            }
        ]
    adapter = SimpleNamespace(
        calls=1, known_usage_calls=1, input_tokens=100, output_tokens=20
    )
    planned = {
        "id": f"{scenario_id}-A1",
        "scenario_id": scenario_id,
        "set": "boundary" if scenario_id == "E13" else "supported",
        "planned_model_exposure": True,
    }

    attempt = _graded_attempt(
        ROOT, scenario, planned, request, report, state, adapter, run_id="leak-probe"
    )
    grade = grade_attempts([planned], [attempt])

    assert False in attempt["unsupported_claim_leakage_assertions"]
    assert "leaked" in attempt["containment_events"]
    assert grade["metrics"]["containment"]["leaked"] == 1
    assert grade["overall_status"] == "fail"


def test_m5_tool_sequence_counts_completed_calls_once_and_ignores_unfinished_request(tmp_path):
    from bi_analyst.live_evaluation import _graded_attempt

    scenario, request, report = _frozen_deterministic_report(tmp_path, "E01")
    trace = [
        {"event": "tool_requested", "tool": "compare_periods"},
        {"event": "tool_completed", "tool": "compare_periods", "evidence_id": "EV_COMPARE"},
        {"event": "tool_requested", "tool": "breakdown_change"},
        {"event": "tool_completed", "tool": "breakdown_change", "evidence_id": "EV_REGION"},
        {"event": "tool_requested", "tool": "breakdown_change"},
    ]
    scored = _graded_attempt(
        ROOT, scenario, {"id": "DEV-TEST", "set": "supported"}, request,
        report, {"trace": trace}, None, run_id="local",
    )

    assert scored["investigation"]["tool_sequence"] == [
        "compare_periods", "breakdown_change",
    ]


def test_e14_live_report_quarantines_frozen_hostile_text_but_keeps_evidence_ids(tmp_path):
    from bi_analyst.live_eval_readiness import load_live_evaluation_config
    from bi_analyst.live_evaluation import (
        BudgetLedger,
        _case_inputs,
        _execute_attempt,
        _graded_attempt,
        _load_frozen_cohort,
    )
    from bi_analyst.store import RunStore

    cohort, requests, contracts, _ = _load_frozen_cohort(ROOT)
    scenario = next(item for item in cohort["scenarios"] if item["id"] == "E14")
    output = tmp_path / "live"
    config = load_live_evaluation_config(_ready_config(tmp_path / "config.json"))
    ledger = BudgetLedger.create(tmp_path / "budget.json", identity="e14", cap_usd="4.50")

    def handler(request):
        payload = json.loads(json.loads(request.content)["input"][0]["content"])
        observations = payload["observations"]
        if not observations:
            action = {"kind": "tool", "tool": "compare_periods", "reason": "Root comparison"}
        else:
            done = {item["scope"].get("dimension") for item in observations}
            todo = [item["id"] for item in payload["dimensions"] if item["id"] not in done]
            if todo:
                action = {
                    "kind": "tool", "tool": "breakdown_change", "dimension": todo[0],
                    "evidence_ids": [observations[0]["evidence_id"]], "reason": "Root breakdown",
                }
            else:
                action = {
                    "kind": "finish", "evidence_ids": [item["evidence_id"] for item in observations],
                    "reason": "Supported descriptive answer",
                }
        return httpx.Response(200, json={
            "status": "completed", "model": "gpt-5.6-luna", "service_tier": "default",
            "usage": {"input_tokens": 100, "output_tokens": 20},
            "output": [{"type": "function_call", "name": "submit_action", "arguments": json.dumps(action)}],
        })

    attempt = _execute_attempt(
        ROOT, output, config, scenario,
        {"id": "E14-A1", "set": "supported", "planned_model_exposure": True},
        cohort, requests, contracts, ledger, "test-only-dummy",
        transport=httpx.MockTransport(handler),
    )
    assert attempt["run_state"] == "completed", attempt["error_code"]
    store = RunStore(output / "run_store", owner="m5-local")
    report = store.read(attempt["run_id"], "agent_report.json")
    state = store.read(attempt["run_id"], "agent_state.json")
    artifact = store.read(attempt["run_id"], "validated_analysis.json")
    forbidden = scenario["output_policy"]["forbidden_output_literals"]
    assert report["presentation_redacted"] is True
    assert all(value not in json.dumps(report) for value in forbidden)
    assert all(value not in json.dumps(state["trace"]) for value in forbidden)
    assert all(value not in json.dumps(item) for item in report["findings"] for value in forbidden)
    accepted = [
        item["candidate"] for item in artifact["findings"]
        if item["validation"]["accepted"]
    ]
    assert all(value not in json.dumps(accepted) for value in forbidden)
    assert any(item.get("label") == "Untrusted Region label" for item in accepted)
    assert scenario["offline_attack_input"]["raw_region_label"] in json.dumps(
        artifact["evidence_registry"]
    )
    assert set(report["root_evidence_ids"]).issubset({item["evidence_id"] for item in state["results"]})
    assert all(attempt["unsupported_claim_leakage_assertions"])
    _fixture, request, _contract = _case_inputs(ROOT, scenario, cohort, requests, contracts)
    leaked_action = deepcopy(state)
    leaked_action["trace"].append({"event": "tool_requested", "reason": scenario["canary"]})
    leaked = _graded_attempt(
        ROOT, scenario, {"id": "E14-A1", "set": "supported"}, request,
        report, leaked_action, None, run_id=attempt["run_id"],
    )
    assert leaked["unsupported_claim_leakage_assertions"][0] is False
