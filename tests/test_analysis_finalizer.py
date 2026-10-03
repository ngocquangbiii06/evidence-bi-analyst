import pytest
from conftest import EXAMPLES

from bi_analyst.analysis_finalizer import (
    finalize_analysis,
    goal_disposition_for_request,
    trusted_analysis_load_context,
)
from bi_analyst.analysis_store import ValidatedAnalysisStore
from bi_analyst.analytics import Analytics
from bi_analyst.contracts import (
    AnalysisTraceEvent,
    DataPolicy,
    ValidatedAnalysisArtifact,
)
from bi_analyst.errors import BIError
from bi_analyst.finding_validation import trusted_evidence_call
from bi_analyst.provider import Action, ModelReply, OpenAIAdapter
from bi_analyst.runtime import AgentRunner
from bi_analyst.store import RunStore
from bi_analyst.workflow import analyze_deterministic, ingest_run


def _test_adapter_policy(dataset):
    return DataPolicy(
        mode="demo_cloud",
        external_llm_enabled=True,
        dataset_class="synthetic",
        approved_dataset_hashes=[dataset.sha256],
        approved_endpoint=OpenAIAdapter.ENDPOINT,
        approved_metrics=["Revenue"],
        approved_dimensions=["Region", "Product"],
    )


class _EvidenceDrivenAdapter:
    name = "t08-evidence-fixture"
    is_live = False

    def invoke(self, payload, schema, max_output_tokens, timeout):
        observations = payload["observations"]
        if not observations:
            action = Action(kind="tool", tool="compare_periods", reason="Compare root periods.")
        else:
            done = {item["scope"].get("dimension") for item in observations}
            todo = [item["id"] for item in payload["dimensions"] if item["id"] not in done]
            if todo:
                action = Action(
                    kind="tool",
                    tool="breakdown_change",
                    dimension=todo[0],
                    reason="Check a requested root dimension.",
                )
            else:
                action = Action(
                    kind="finish",
                    reason="The requested scopes have evidence.",
                    evidence_ids=[item["evidence_id"] for item in observations],
                )
        return ModelReply(action.model_dump_json())


class _FakeLiveAdapter(_EvidenceDrivenAdapter):
    name = "t08-offline-live-mode-fixture"
    model = "offline-fixture"
    is_live = True

    def __init__(self):
        self.calls = 0

    def invoke(self, payload, schema, max_output_tokens, timeout):
        self.calls += 1
        return super().invoke(payload, schema, max_output_tokens, timeout)


class _AggregateFirstAdapter:
    name = "t08-aggregate-first-fixture"
    is_live = False

    def invoke(self, payload, schema, max_output_tokens, timeout):
        observations = payload["observations"]
        tools = {item["tool"] for item in observations}
        if "aggregate_metric" not in tools:
            action = Action(
                kind="tool",
                tool="aggregate_metric",
                period="previous",
                reason="Check the previous-period aggregate.",
            )
        elif "compare_periods" not in tools:
            action = Action(kind="tool", tool="compare_periods", reason="Compare periods.")
        else:
            checked_dimensions = {
                item["scope"].get("dimension")
                for item in observations
                if item["tool"] == "breakdown_change"
            }
            todo = [
                item["id"]
                for item in payload["dimensions"]
                if item["id"] not in checked_dimensions
            ]
            if todo:
                action = Action(
                    kind="tool",
                    tool="breakdown_change",
                    dimension=todo[0],
                    reason="Check a requested dimension.",
                )
            else:
                action = Action(
                    kind="finish",
                    reason="The requested scopes have evidence.",
                    evidence_ids=[item["evidence_id"] for item in observations],
                )
        return ModelReply(action.model_dump_json())


class _RedundantPeriodAdapter:
    name = "t08-redundant-period-fixture"
    is_live = False

    def invoke(self, payload, schema, max_output_tokens, timeout):
        observations = payload["observations"]
        if not any(item["tool"] == "compare_periods" for item in observations):
            action = Action(
                kind="tool",
                tool="compare_periods",
                period="previous",
                reason="Compare both periods.",
            )
        else:
            checked_dimensions = {
                item["scope"].get("dimension")
                for item in observations
                if item["tool"] == "breakdown_change"
            }
            todo = [
                item["id"]
                for item in payload["dimensions"]
                if item["id"] not in checked_dimensions
            ]
            if todo:
                action = Action(
                    kind="tool",
                    tool="breakdown_change",
                    dimension=todo[0],
                    period="previous",
                    reason="Check a requested dimension.",
                )
            else:
                action = Action(
                    kind="finish",
                    reason="The requested scopes have evidence.",
                    evidence_ids=[item["evidence_id"] for item in observations],
                )
        return ModelReply(action.model_dump_json())


def _evidence_calls(contract, request, results_and_requests):
    calls = {}
    for result, evidence_request in results_and_requests:
        calls[result["evidence_id"]] = trusted_evidence_call(
            contract,
            evidence_request,
            result["tool"],
            dimension=result["scope"].get("dimension"),
        )
    return calls


def _finalize_direct(
    tmp_path,
    dataset,
    contract,
    request,
    results_and_requests,
    *,
    mode="deterministic",
    investigation_trace=None,
    execution_status="succeeded",
    errors=None,
    goal_disposition="supported_descriptive",
):
    run_store = RunStore(tmp_path / "runtime")
    run_id = run_store.create()
    results = [result for result, _ in results_and_requests]
    return finalize_analysis(
        run_store,
        run_id,
        request,
        contract,
        dataset.sha256,
        mode=mode,
        results=results,
        evidence_calls=_evidence_calls(contract, request, results_and_requests),
        investigation_trace=investigation_trace or [],
        execution_status=execution_status,
        goal_disposition=goal_disposition,
        errors=errors or [],
        usage={"tool_calls": len(results), "model_calls": 0},
    )


def test_deterministic_and_agent_modes_share_finalized_artifact(
    tmp_path, dataset, contract, request_spec
):
    policy = _test_adapter_policy(dataset)
    deterministic_store = RunStore(tmp_path / "deterministic")
    deterministic_run = ingest_run(
        EXAMPLES / "sales.csv", contract, policy, deterministic_store
    )
    analyze_deterministic(deterministic_run, deterministic_store, request_spec)
    deterministic_artifact = ValidatedAnalysisArtifact.model_validate(
        deterministic_store.read(deterministic_run, "validated_analysis.json")
    )

    agent_store = RunStore(tmp_path / "agent")
    agent_run = ingest_run(EXAMPLES / "sales.csv", contract, policy, agent_store)
    AgentRunner(agent_store, _EvidenceDrivenAdapter()).run(agent_run, request_spec)
    agent_artifact = ValidatedAnalysisArtifact.model_validate(
        agent_store.read(agent_run, "validated_analysis.json")
    )

    assert deterministic_artifact.mode == "deterministic"
    assert agent_artifact.mode == "test_adapter"
    assert deterministic_artifact.sufficiency_status == agent_artifact.sufficiency_status
    assert deterministic_artifact.root_evidence_ids == agent_artifact.root_evidence_ids
    assert deterministic_artifact.obligations == agent_artifact.obligations
    assert [
        (item.candidate.claim_type, item.candidate.scope, item.candidate.delta_minor)
        for item in deterministic_artifact.findings
    ] == [
        (item.candidate.claim_type, item.candidate.scope, item.candidate.delta_minor)
        for item in agent_artifact.findings
    ]


def test_unreviewed_live_agent_is_blocked_before_adapter_call(
    tmp_path, dataset, contract, request_spec
):
    policy = _test_adapter_policy(dataset).model_copy(
        update={
            "max_cost_usd": 1.0,
            "input_usd_per_million": 1.0,
            "output_usd_per_million": 1.0,
        }
    )
    store = RunStore(tmp_path / "live-agent-mode")
    run_id = ingest_run(EXAMPLES / "sales.csv", contract, policy, store)
    adapter = _FakeLiveAdapter()

    with pytest.raises(BIError) as error:
        AgentRunner(store, adapter).run(run_id, request_spec)

    assert error.value.code == "EVALUATION_NOT_APPROVED"
    assert adapter.calls == 0


def test_completed_aggregate_first_agent_run_resumes_from_trusted_evidence(
    tmp_path, dataset, contract, request_spec
):
    policy = _test_adapter_policy(dataset)
    store = RunStore(tmp_path / "aggregate-first-agent")
    run_id = ingest_run(EXAMPLES / "sales.csv", contract, policy, store)
    runner = AgentRunner(store, _AggregateFirstAdapter())

    report = runner.run(run_id, request_spec)
    artifact = ValidatedAnalysisArtifact.model_validate(
        store.read(run_id, "validated_analysis.json")
    )
    resumed = runner.run(run_id, request_spec, resume=True)

    assert report["status"] == "COMPLETED"
    assert any(result["tool"] == "aggregate_metric" for result in artifact.evidence_registry.values())
    assert resumed == report


def test_redundant_period_on_compare_and_breakdown_finalizes_normally(
    tmp_path, dataset, contract, request_spec
):
    policy = _test_adapter_policy(dataset)
    store = RunStore(tmp_path / "redundant-period-agent")
    run_id = ingest_run(EXAMPLES / "sales.csv", contract, policy, store)

    report = AgentRunner(store, _RedundantPeriodAdapter()).run(run_id, request_spec)
    artifact = ValidatedAnalysisArtifact.model_validate(
        store.read(run_id, "validated_analysis.json")
    )

    assert report["status"] == "COMPLETED"
    assert artifact.execution_status == "succeeded"
    assert artifact.sufficiency_status == "completed"
    assert store.manifest(run_id)["status"] == "COMPLETED"
    assert {store_result["tool"] for store_result in artifact.evidence_registry.values()} == {
        "compare_periods",
        "breakdown_change",
    }


@pytest.mark.parametrize("mode", ["deterministic", "agent"])
def test_causal_question_is_gated_before_either_caller_can_complete(
    tmp_path, dataset, contract, request_spec, mode
):
    causal_request = request_spec.model_copy(
        update={"question": "What caused Revenue to increase?"}
    )
    policy = _test_adapter_policy(dataset)
    store = RunStore(tmp_path / f"causal-{mode}")
    run_id = ingest_run(EXAMPLES / "sales.csv", contract, policy, store)

    if mode == "deterministic":
        report = analyze_deterministic(run_id, store, causal_request)
    else:
        report = AgentRunner(store, _EvidenceDrivenAdapter()).run(run_id, causal_request)
    artifact = ValidatedAnalysisArtifact.model_validate(
        store.read(run_id, "validated_analysis.json")
    )

    assert report["status"] == "ABSTAINED"
    assert artifact.goal_disposition == "unsupported_causal"
    assert artifact.sufficiency_status == "abstained"
    assert "goal.causal_explanation" in artifact.obligations.missing
    assert artifact.accepted_finding_ids == []


@pytest.mark.parametrize("mode", ["deterministic", "agent"])
@pytest.mark.parametrize(
    "question",
    [
        "Vì sao doanh thu thay đổi và nguyên nhân là gì?",
        "Tại sao Revenue giảm?",
        "Nguyên nhân khiến doanh thu tăng là gì?",
        "Doanh thu giảm do đâu?",
        "Lý do doanh thu thay đổi?",
        "Lí do doanh thu giảm?",
        "Nguyên do doanh thu tăng là gì?",
    ],
)
def test_vietnamese_causal_question_is_gated_before_either_caller_can_complete(
    tmp_path, dataset, contract, request_spec, mode, question
):
    causal_request = request_spec.model_copy(update={"question": question})
    policy = _test_adapter_policy(dataset)
    store = RunStore(tmp_path / f"causal-vi-{mode}")
    run_id = ingest_run(EXAMPLES / "sales.csv", contract, policy, store)

    if mode == "deterministic":
        report = analyze_deterministic(run_id, store, causal_request)
    else:
        report = AgentRunner(store, _EvidenceDrivenAdapter()).run(run_id, causal_request)
    artifact = ValidatedAnalysisArtifact.model_validate(
        store.read(run_id, "validated_analysis.json")
    )

    assert report["status"] == "ABSTAINED"
    assert artifact.goal_disposition == "unsupported_causal"
    assert artifact.sufficiency_status == "abstained"
    assert "goal.causal_explanation" in artifact.obligations.missing
    assert artifact.accepted_finding_ids == []


@pytest.mark.parametrize(
    "question",
    [
        "Doanh thu thay đổi thế nào và nhóm nào đóng góp nhiều nhất?",
        "Nhóm nào đóng góp nhiều nhất vào chênh lệch?",
        "Doanh thu kỳ này so với kỳ trước ra sao?",
        "What changed in Revenue and which group contributed most?",
        "Tốc độ đầu kỳ so với cuối kỳ thế nào?",
        "Đơn vị đầu tiên có doanh thu cao nhất là gì?",
        "Doanh thu do đầu mối nào đóng góp nhiều nhất?",
        "Khu vực nào dẫn đầu về doanh thu?",
    ],
)
def test_descriptive_questions_stay_supported_descriptive(request_spec, question):
    request = request_spec.model_copy(update={"question": question})

    assert goal_disposition_for_request(request) == "supported_descriptive"


@pytest.mark.parametrize(
    "question",
    [
        "VÌ SAO DOANH THU GIẢM?",
        "Vi sao doanh thu giam?",
        "Tai sao doanh thu giam?",
        "Nguyen nhan doanh thu tang la gi?",
        "Doanh thu giam do dau?",
        "Doanh thu giảm vì đâu?",
        "Ly do doanh thu giam?",
        "Nguyên cớ doanh thu giảm?",
        "Vì sao doanh thu giảm?",
        "Doanh thu giảm do đâu?",
    ],
)
def test_vietnamese_causal_variants_are_gated_directly(request_spec, question):
    request = request_spec.model_copy(update={"question": question})

    assert goal_disposition_for_request(request) == "unsupported_causal"


def test_missing_required_dimension_cannot_complete(
    tmp_path, dataset, contract, request_spec
):
    engine = Analytics(dataset, contract)
    comparison = engine.compare_periods(request_spec)
    region = engine.breakdown_change(request_spec, "Region")
    artifact = _finalize_direct(
        tmp_path,
        dataset,
        contract,
        request_spec,
        [(comparison, request_spec), (region, request_spec)],
    )

    assert artifact.sufficiency_status == "partial"
    assert "dimension.Product.breakdown" in artifact.obligations.missing
    assert artifact.root_evidence_ids == [comparison["evidence_id"], region["evidence_id"]]


def test_narrow_comparison_before_root_is_retained_but_cannot_fulfill_root(
    tmp_path, dataset, contract, request_spec
):
    engine = Analytics(dataset, contract)
    narrow_request = request_spec.model_copy(
        update={"filters": {"Region": ["North"]}}
    )
    narrow = engine.compare_periods(narrow_request)
    root = engine.compare_periods(request_spec)
    region = engine.breakdown_change(request_spec, "Region")
    product = engine.breakdown_change(request_spec, "Product")
    artifact = _finalize_direct(
        tmp_path,
        dataset,
        contract,
        request_spec,
        [
            (narrow, narrow_request),
            (root, request_spec),
            (region, request_spec),
            (product, request_spec),
        ],
    )

    assert artifact.sufficiency_status == "completed"
    assert narrow["evidence_id"] in artifact.evidence_registry
    assert narrow["evidence_id"] not in artifact.root_evidence_ids
    assert artifact.root_evidence_ids == [
        root["evidence_id"],
        region["evidence_id"],
        product["evidence_id"],
    ]
    assert narrow["evidence_id"] not in artifact.obligations.evidence_by_obligation[
        "overall.delta"
    ]
    narrow_findings = [
        item
        for item in artifact.findings
        if item.candidate.evidence_id == narrow["evidence_id"]
    ]
    assert narrow_findings
    assert all(item.validation.accepted for item in narrow_findings)
    assert all(item.candidate.scope.filters == {"Region": ["North"]} for item in narrow_findings)


def test_only_narrowed_finish_citations_cannot_complete_root_request(
    tmp_path, dataset, contract, request_spec
):
    engine = Analytics(dataset, contract)
    narrow_request = request_spec.model_copy(
        update={"filters": {"Region": ["North"]}}
    )
    narrow_comparison = engine.compare_periods(narrow_request)
    narrow_region = engine.breakdown_change(narrow_request, "Region")
    narrow_product = engine.breakdown_change(narrow_request, "Product")
    results = [narrow_comparison, narrow_region, narrow_product]
    finish = AnalysisTraceEvent(
        revision=4,
        kind="finish",
        evidence_ids=[item["evidence_id"] for item in results],
    )
    artifact = _finalize_direct(
        tmp_path,
        dataset,
        contract,
        request_spec,
        [(item, narrow_request) for item in results],
        mode="test_adapter",
        investigation_trace=[finish],
    )

    assert artifact.sufficiency_status == "abstained"
    assert artifact.obligations.fulfilled == []
    assert "overall.delta" in artifact.obligations.missing
    assert artifact.root_evidence_ids == []
    assert set(artifact.evidence_registry) == {item["evidence_id"] for item in results}
    assert artifact.accepted_finding_ids
    assert all(
        artifact.evidence_registry[evidence_id]["scope"]["filters"]
        == {"Region": ["North"]}
        for evidence_id in artifact.root_evidence_ids
    )


@pytest.mark.parametrize(
    "execution_status,error_code",
    [("failed", "TOOL_TIMEOUT"), ("cancelled", "CANCELLED")],
)
def test_timeout_and_cancel_remain_operational_failure_not_abstention(
    tmp_path, dataset, contract, request_spec, execution_status, error_code
):
    artifact = _finalize_direct(
        tmp_path,
        dataset,
        contract,
        request_spec,
        [],
        mode="test_adapter",
        execution_status=execution_status,
        errors=[{"code": error_code, "stage": "tool", "message": "Execution stopped."}],
    )

    assert artifact.execution_status == execution_status
    assert artifact.sufficiency_status is None
    assert artifact.errors[0].code == error_code
    assert artifact.accepted_finding_ids == []


def test_operational_failure_blocks_previously_valid_finding_as_not_checked(
    tmp_path, dataset, contract, request_spec
):
    comparison = Analytics(dataset, contract).compare_periods(request_spec)
    artifact = _finalize_direct(
        tmp_path,
        dataset,
        contract,
        request_spec,
        [(comparison, request_spec)],
        execution_status="failed",
        errors=[{"code": "TOOL_TIMEOUT", "stage": "tool", "message": "Timed out."}],
    )

    assert artifact.sufficiency_status is None
    assert artifact.accepted_finding_ids == []
    assert artifact.rejected_finding_ids
    for record in artifact.findings:
        assert record.validation.accepted is False
        assert "EXECUTION_INCOMPLETE" in record.validation.reasons
        assert "failed" not in {
            record.validation.numerical,
            record.validation.evidence_linkage,
            record.validation.scope,
            record.validation.interpretation,
        }
        assert "not_checked" in {
            record.validation.numerical,
            record.validation.evidence_linkage,
            record.validation.scope,
            record.validation.interpretation,
        }


@pytest.mark.parametrize("block_reason", ["execution", "unresolved", "causal"])
def test_blocked_m1_finding_round_trips_through_validated_store(
    tmp_path, dataset, contract, request_spec, block_reason
):
    request = request_spec
    if block_reason == "causal":
        request = request.model_copy(
            update={"question": "What caused Revenue to increase?"}
        )
    comparison = Analytics(dataset, contract).compare_periods(request)
    evidence_calls = _evidence_calls(contract, request, [(comparison, request)])
    store = RunStore(tmp_path / f"blocked-{block_reason}")
    run_id = store.create()
    options = {}
    if block_reason == "execution":
        options = {
            "execution_status": "failed",
            "errors": [
                {"code": "TOOL_TIMEOUT", "stage": "tool", "message": "Timed out."}
            ],
        }
    elif block_reason == "unresolved":
        options = {
            "goal_disposition": "unresolved",
            "clarification_request": "Please confirm the metric mapping.",
        }
    else:
        options = {"goal_disposition": "unsupported_causal"}

    artifact = finalize_analysis(
        store,
        run_id,
        request,
        contract,
        dataset.sha256,
        mode="deterministic",
        results=[comparison],
        evidence_calls=evidence_calls,
        usage={"tool_calls": 1, "model_calls": 0},
        **options,
    )
    load_context = trusted_analysis_load_context(
        dataset.sha256, contract, request, evidence_calls
    )

    loaded = ValidatedAnalysisStore(store).load(run_id, load_context)

    assert loaded.content_fingerprint == artifact.content_fingerprint
    assert loaded.findings == artifact.findings
    assert loaded.accepted_finding_ids == []


def test_rejected_candidate_and_validation_reasons_survive_finalization(
    tmp_path, dataset, contract, request_spec
):
    comparison = Analytics(dataset, contract).compare_periods(request_spec)
    comparison["data"]["delta_minor"] += 1
    artifact = _finalize_direct(
        tmp_path,
        dataset,
        contract,
        request_spec,
        [(comparison, request_spec)],
    )

    assert artifact.rejected_finding_ids
    assert not artifact.accepted_finding_ids
    assert any(
        record.validation.reasons
        for record in artifact.findings
        if record.candidate.finding_id in artifact.rejected_finding_ids
    )
    assert any(
        "EVIDENCE_ID_INTEGRITY_FAILED" in record.validation.reasons
        for record in artifact.findings
    )


def test_unsupported_causal_goal_abstains_and_explicitly_disclaims_causation(
    tmp_path, dataset, contract, request_spec
):
    causal_request = request_spec.model_copy(
        update={"question": "What caused Revenue to increase?"}
    )
    engine = Analytics(dataset, contract)
    comparison = engine.compare_periods(causal_request)
    region = engine.breakdown_change(causal_request, "Region")
    product = engine.breakdown_change(causal_request, "Product")
    artifact = _finalize_direct(
        tmp_path,
        dataset,
        contract,
        causal_request,
        [
            (comparison, causal_request),
            (region, causal_request),
            (product, causal_request),
        ],
        goal_disposition="unsupported_causal",
    )

    assert artifact.sufficiency_status == "abstained"
    assert "goal.causal_explanation" in artifact.obligations.missing
    assert artifact.accepted_finding_ids == []
    assert any("causal" in limitation.casefold() for limitation in artifact.limitations)


def test_completed_legacy_resume_without_authoritative_artifact_is_rejected(
    tmp_path, dataset, contract, request_spec
):
    policy = _test_adapter_policy(dataset)
    store = RunStore(tmp_path / "runtime")
    run_id = ingest_run(EXAMPLES / "sales.csv", contract, policy, store)
    runner = AgentRunner(store, _EvidenceDrivenAdapter())
    runner.run(run_id, request_spec)
    artifact_path = store._path(run_id) / "validated_analysis.json"
    artifact_path.unlink()

    with pytest.raises(BIError) as error:
        runner.run(run_id, request_spec, resume=True)

    assert error.value.code in {"ARTIFACT_MISSING", "LEGACY_ARTIFACT"}

