import json

import pytest
from conftest import EXAMPLES
from test_agent_security import cloud_policy

from bi_analyst.bi import export_powerbi
from bi_analyst.errors import BIError
from bi_analyst.provider import ModelReply
from bi_analyst.stages import BIChoice, SemanticChoice, plan_bi, review_semantics
from bi_analyst.store import RunStore
from bi_analyst.workflow import analyze_deterministic, ingest_run


class StageFixture:
    name = "structured-stage-fixture"
    is_live = False

    def __init__(self, purpose, invalid=False):
        self.purpose = purpose
        self.invalid = invalid
        self.payloads = []

    def invoke(self, payload, *args):
        self.payloads.append(payload)
        if self.purpose == "semantic_review":
            columns = payload["columns"]
            by_name = {c["approved_name"]: c for c in columns if c["approved_name"]}
            choice = SemanticChoice(
                date_column_token=by_name["OrderDate"]["column_token"],
                date_format="%Y-%m-%d",
                row_key_tokens=[by_name["LineID"]["column_token"]],
                metric_column_token=by_name["Revenue"]["column_token"],
                dimension_tokens=[by_name["Region"]["column_token"]],
                evidence_ids=[c["evidence_id"] for c in columns],
                questions=["Confirm business grain and currency."],
            )
        else:
            choice = BIChoice(
                prominent_dimensions=["Unknown"] if self.invalid else ["Product", "Region"],
                emphasis="change",
                evidence_ids=[r["evidence_id"] for r in payload["observations"]],
                summary="Inspect the largest observed movements.",
            )
        return ModelReply(choice.model_dump_json())


def test_optional_stages_require_explicit_approval(tmp_path, dataset):
    adapter = StageFixture("semantic_review")
    with pytest.raises(BIError) as error:
        review_semantics(dataset, cloud_policy(dataset), RunStore(tmp_path / "runtime"), adapter)
    assert error.value.code == "STAGE_DENIED"
    assert adapter.payloads == []


def test_semantic_review_only_sends_approved_headers_and_statistics(tmp_path, dataset):
    policy = cloud_policy(dataset)
    policy.approved_stages.append("semantic_review")
    policy.approved_schema_columns = ["LineID", "OrderDate", "Revenue", "Region"]
    adapter = StageFixture("semantic_review")
    proposal = review_semantics(dataset, policy, RunStore(tmp_path / "runtime"), adapter)
    assert proposal["confirmed"] is False
    assert proposal["mappings"]["date_column"] == "OrderDate"
    text = json.dumps(adapter.payloads)
    assert all(value not in text for value in ["CustomerID", "C001", "North", "South", "OrderID"])
    assert proposal["unknowns"]


def test_llm_layout_stage_and_export_bypass_are_disabled(
    tmp_path, dataset, contract, request_spec
):
    policy = cloud_policy(dataset)
    policy.approved_stages.append("bi_planning")
    store = RunStore(tmp_path / "runtime")
    run_id = ingest_run(EXAMPLES / "sales.csv", contract, policy, store)
    adapter = StageFixture("bi_planning")
    with pytest.raises(BIError) as error:
        plan_bi(run_id, store, request_spec, adapter)
    assert error.value.code == "STAGE_DISABLED"
    assert adapter.payloads == []
    assert not (store._path(run_id) / "bi_plan.json").exists()

    analyze_deterministic(run_id, store, request_spec)
    with pytest.raises(BIError) as error:
        export_powerbi(run_id, store, tmp_path / "planned", request_spec, use_plan=True)
    assert error.value.code == "BI_LAYOUT_DISABLED"

    output = tmp_path / "project"
    export_powerbi(run_id, store, output, request_spec)
    visuals = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (output / "EvidenceBI.Report/definition/pages").glob("*/visuals/*/visual.json")
    ]
    visual = next(
        item
        for item in visuals
        if item["visual"]["visualType"] == "barChart"
        and item["visual"]["query"]["queryState"]["Category"]["projections"][0]["field"]["Column"][
            "Property"
        ]
        == "Product"
    )
    assert (
        visual["visual"]["query"]["queryState"]["Category"]["projections"][0]["field"]["Column"][
            "Property"
        ]
        == "Product"
    )
    data_visuals = [
        item for item in visuals if item["visual"].get("visualType") != "textbox"
    ]
    textboxes = [
        item for item in visuals if item["visual"].get("visualType") == "textbox"
    ]
    assert len(visuals) == 13
    assert len(data_visuals) == 9
    assert len(textboxes) == 4


def test_disabled_bi_planner_never_sends_a_payload(tmp_path, dataset, contract, request_spec):
    policy = cloud_policy(dataset)
    policy.approved_stages.append("bi_planning")
    store = RunStore(tmp_path / "runtime")
    run_id = ingest_run(EXAMPLES / "sales.csv", contract, policy, store)
    adapter = StageFixture("bi_planning", invalid=True)
    with pytest.raises(BIError) as error:
        plan_bi(run_id, store, request_spec, adapter)
    assert error.value.code == "STAGE_DISABLED"
    assert adapter.payloads == []
    assert not (store._path(run_id) / "bi_plan.json").exists()


def test_semantic_stage_checks_original_policy_before_transport(tmp_path, dataset):
    policy = cloud_policy(dataset)
    policy.approved_stages.append("semantic_review")
    source = tmp_path / "policy.json"
    changed = policy.model_copy(update={"revision": 2})
    source.write_text(changed.model_dump_json())
    adapter = StageFixture("semantic_review")
    with pytest.raises(BIError) as error:
        review_semantics(
            dataset, policy, RunStore(tmp_path / "runtime"), adapter, policy_path=source
        )
    assert error.value.code == "POLICY_CHANGED"
    assert adapter.payloads == []
