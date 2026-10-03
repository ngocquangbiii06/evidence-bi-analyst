import base64
import importlib.util
import json
import re
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import EXAMPLES
from test_agent_security import cloud_policy

from bi_analyst.analytics import Analytics
from bi_analyst.bi import _format_pattern, _scope_label, build_model, build_report, export_powerbi
from bi_analyst.contracts import AnalysisScope, Period
from bi_analyst.data import load_csv
from bi_analyst.errors import BIError
from bi_analyst.provider import Action, ModelReply
from bi_analyst.runtime import AgentRunner
from bi_analyst.store import RunStore
from bi_analyst.workflow import analyze_deterministic, ingest_run
from scripts.validate_powerbi import _interaction_contract_failures


def _run_with_analysis(tmp_path, contract, policy, request_spec):
    store = RunStore(tmp_path / "runtime")
    run_id = ingest_run(EXAMPLES / "sales.csv", contract, policy, store)
    report = analyze_deterministic(run_id, store, request_spec)
    return store, run_id, report


def test_model_data_and_relationships(dataset, contract, request_spec):
    engine = Analytics(dataset, contract)
    model, spec = build_model(engine, request_spec)
    tables = {t["name"]: t for t in model["model"]["tables"]}
    assert set(tables) == {
        "FactSales",
        "DimDate",
        "DimRegion",
        "DimProduct",
        "Evidence",
        "AnalysisInfo",
    }
    expression = tables["FactSales"]["partitions"][0]["source"]["expression"]
    encoded = expression[1].split('"')[1]
    rows = json.loads(base64.b64decode(encoded))
    assert len(rows) == 8
    assert sum(int(r[-1]) for r in rows) == 1600
    assert all(
        r["crossFilteringBehavior"] == "oneDirection" for r in model["model"]["relationships"]
    )
    measures = {measure["name"]: measure for measure in tables["FactSales"]["measures"]}
    change_dax = measures["Revenue Change"]["expression"]
    assert "VAR CurrentAmount =" in change_dax
    assert "VAR Current =" not in change_dax
    assert all(k["validation"]["execution"] == "not_checked" for k in spec["kpis"])


def test_project_validates_against_official_schemas(
    tmp_path, dataset, contract, request_spec, policy
):
    store = RunStore(tmp_path / "runtime")
    run_id = ingest_run(EXAMPLES / "sales.csv", contract, policy, store)
    analyze_deterministic(run_id, store, request_spec)
    dest = tmp_path / "PowerBI"
    export_powerbi(run_id, store, dest, request_spec)
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "validate_powerbi.py"
    spec = importlib.util.spec_from_file_location("schema_validation", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.validate_project(dest)
    assert not result["failures"], result["failures"]
    assert result["schema_files_checked"] >= 10
    references = module.validate_references(dest)
    assert not references["failures"], references["failures"]
    manifest = json.loads((dest / "export_manifest.json").read_text())
    assert manifest["status"] == "generated_not_executed"
    platform = json.loads((dest / "EvidenceBI.Report" / ".platform").read_text())
    assert platform["metadata"] == {"type": "Report", "displayName": "EvidenceBI"}
    assert platform["config"]["version"] == "2.0"
    definition = dest / "EvidenceBI.Report" / "definition"
    version = json.loads((definition / "version.json").read_text())
    assert version["version"] == "2.0.0"
    pages = json.loads((definition / "pages" / "pages.json").read_text())
    assert len(pages["pageOrder"]) == 2
    assert pages["activePageName"] == pages["pageOrder"][0]
    assert all(re.fullmatch(r"[a-f0-9]{20}", page_id) for page_id in pages["pageOrder"])
    visual_files = list((definition / "pages").glob("*/visuals/*/visual.json"))
    assert len(visual_files) == 13
    visuals = [json.loads(path.read_text(encoding="utf-8")) for path in visual_files]
    assert all(re.fullmatch(r"[a-f0-9]{20}", visual["name"]) for visual in visuals)
    cards = [
        visual for visual in visuals if visual.get("visual", {}).get("visualType") == "cardVisual"
    ]
    assert len(cards) == 4
    assert all(set(card["visual"]["query"]["queryState"]) == {"Data"} for card in cards)
    assert sum(visual["visual"]["visualType"] == "textbox" for visual in visuals) == 4
    assert sum(visual["visual"]["visualType"] == "columnChart" for visual in visuals) == 1


def test_export_requires_an_authoritative_analysis_artifact(
    tmp_path, contract, policy, request_spec
):
    store = RunStore(tmp_path / "runtime")
    run_id = ingest_run(EXAMPLES / "sales.csv", contract, policy, store)

    with pytest.raises(BIError) as error:
        export_powerbi(run_id, store, tmp_path / "missing", request_spec)

    assert error.value.code == "ARTIFACT_UNAVAILABLE"
    assert not (tmp_path / "missing").exists()


def test_export_rejects_abstained_analysis_artifact(tmp_path, contract, policy, request_spec):
    store = RunStore(tmp_path / "runtime")
    run_id = ingest_run(EXAMPLES / "sales.csv", contract, policy, store)
    causal_request = request_spec.model_copy(update={"question": "Why did revenue change?"})
    report = analyze_deterministic(run_id, store, causal_request)
    assert report["status"] == "ABSTAINED"

    with pytest.raises(BIError) as error:
        export_powerbi(run_id, store, tmp_path / "abstained", causal_request)

    assert error.value.code == "EXPORT_NOT_ELIGIBLE"
    assert not (tmp_path / "abstained").exists()


def test_export_request_must_match_the_validated_artifact(
    tmp_path, contract, policy, request_spec
):
    store, run_id, _ = _run_with_analysis(tmp_path, contract, policy, request_spec)
    changed_request = request_spec.model_copy(update={"filters": {"Region": ["North"]}})

    with pytest.raises(BIError) as error:
        export_powerbi(run_id, store, tmp_path / "stale-request", changed_request)

    assert error.value.code == "STALE_ARTIFACT"
    assert not (tmp_path / "stale-request").exists()


def test_export_blocks_stale_source_snapshot(tmp_path, contract, policy, request_spec):
    store, run_id, _ = _run_with_analysis(tmp_path, contract, policy, request_spec)
    dataset_path = store._path(run_id) / "dataset.csv"
    dataset_path.write_bytes(dataset_path.read_bytes().rstrip(b"\n"))

    with pytest.raises(BIError) as error:
        export_powerbi(run_id, store, tmp_path / "stale-source", request_spec)

    assert error.value.code == "DATASET_CHANGED"
    assert not (tmp_path / "stale-source").exists()


def test_export_rejects_partial_analysis_artifact(tmp_path, contract, policy, request_spec):
    from bi_analyst.analysis_finalizer import finalize_analysis
    from bi_analyst.finding_validation import trusted_evidence_call
    from bi_analyst.workflow import open_engine

    store = RunStore(tmp_path / "runtime")
    run_id = ingest_run(EXAMPLES / "sales.csv", contract, policy, store)
    engine, _ = open_engine(run_id, store)
    request = request_spec.model_copy(update={"dimensions": ["Region", "Product"]})
    results = [engine.compare_periods(request), engine.breakdown_change(request, "Region")]
    evidence_calls = {
        results[0]["evidence_id"]: trusted_evidence_call(
            contract, request, "compare_periods"
        ).model_dump(mode="json"),
        results[1]["evidence_id"]: trusted_evidence_call(
            contract, request, "breakdown_change", dimension="Region"
        ).model_dump(mode="json"),
    }
    artifact = finalize_analysis(
        store,
        run_id,
        request,
        contract,
        engine.dataset.sha256,
        mode="deterministic",
        results=results,
        evidence_calls=evidence_calls,
    )
    assert artifact.sufficiency_status == "partial"
    store.update(run_id, status="PARTIAL", analysis_mode="deterministic")

    with pytest.raises(BIError) as error:
        export_powerbi(run_id, store, tmp_path / "partial", request)

    assert error.value.code == "EXPORT_NOT_ELIGIBLE"
    assert not (tmp_path / "partial").exists()


def test_export_rejects_needs_input_analysis_artifact(tmp_path, contract, policy, request_spec):
    from bi_analyst.analysis_finalizer import finalize_analysis
    from bi_analyst.workflow import open_engine

    store = RunStore(tmp_path / "runtime")
    run_id = ingest_run(EXAMPLES / "sales.csv", contract, policy, store)
    engine, _ = open_engine(run_id, store)
    artifact = finalize_analysis(
        store,
        run_id,
        request_spec,
        contract,
        engine.dataset.sha256,
        mode="deterministic",
        results=[],
        evidence_calls={},
        goal_disposition="unresolved",
        clarification_request="Confirm the intended business meaning before continuing.",
    )
    assert artifact.sufficiency_status == "needs_input"
    store.update(run_id, status="NEEDS_INPUT", analysis_mode="deterministic")

    with pytest.raises(BIError) as error:
        export_powerbi(run_id, store, tmp_path / "needs-input", request_spec)

    assert error.value.code == "EXPORT_NOT_ELIGIBLE"
    assert not (tmp_path / "needs-input").exists()


def test_export_does_not_recompute_analytics_after_finalization(
    tmp_path, contract, policy, request_spec, monkeypatch
):
    store, run_id, _ = _run_with_analysis(tmp_path, contract, policy, request_spec)

    def fail_if_recomputed(*args, **kwargs):
        pytest.fail("export must consume the finalized evidence registry")

    monkeypatch.setattr(Analytics, "compare_periods", fail_if_recomputed)
    monkeypatch.setattr(Analytics, "breakdown_change", fail_if_recomputed)

    result = export_powerbi(run_id, store, tmp_path / "no-recompute", request_spec)

    assert Path(result["project"]).exists()


def test_export_rejects_coherently_rehashed_deterministic_evidence(
    tmp_path, contract, policy, request_spec
):
    from decimal import Decimal

    from bi_analyst.analysis_finalizer import finalize_analysis
    from bi_analyst.contracts import fingerprint
    from bi_analyst.finding_validation import trusted_evidence_call

    store, run_id, _ = _run_with_analysis(tmp_path, contract, policy, request_spec)
    original = store.read(run_id, "validated_analysis.json")
    forged_results = json.loads(json.dumps(list(original["evidence_registry"].values())))
    id_map = {}
    scale = original["root_scope"]["scale"]

    def double_amounts(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.endswith("_minor") and isinstance(item, int) and not isinstance(item, bool):
                    value[key] = item * 2
                elif key in {"amount", "delta", "previous", "current"} and isinstance(
                    item, str
                ):
                    value[key] = format(Decimal(item) * 2, f".{scale}f")
                else:
                    double_amounts(item)
        elif isinstance(value, list):
            for item in value:
                double_amounts(item)

    for result in forged_results:
        old_id = result["evidence_id"]
        double_amounts(result["data"])
        body = {key: value for key, value in result.items() if key != "evidence_id"}
        result["evidence_id"] = "EV_" + fingerprint(body)[:24]
        id_map[old_id] = result["evidence_id"]

    evidence_calls = {}
    for result in forged_results:
        dimension = result["scope"].get("dimension")
        evidence_calls[result["evidence_id"]] = trusted_evidence_call(
            contract, request_spec, result["tool"], dimension=dimension
        ).model_dump(mode="json")

    finalize_analysis(
        store,
        run_id,
        request_spec,
        contract,
        original["dataset_hash"],
        mode="deterministic",
        results=forged_results,
        evidence_calls=evidence_calls,
    )

    forged = store.read(run_id, "validated_analysis.json")
    assert forged["content_fingerprint"] != original["content_fingerprint"]
    assert forged["accepted_finding_ids"]
    assert forged["evidence_registry"][id_map[original["root_evidence_ids"][0]]]["data"] != original[
        "evidence_registry"
    ][original["root_evidence_ids"][0]]["data"]

    with pytest.raises(BIError) as error:
        export_powerbi(run_id, store, tmp_path / "forged-evidence", request_spec)

    assert error.value.code in {"TAMPERED_ARTIFACT", "STALE_ARTIFACT"}
    assert not (tmp_path / "forged-evidence").exists()


def test_export_evidence_maps_accepted_findings_and_artifact_scope(
    tmp_path, contract, policy, request_spec
):
    store, run_id, _ = _run_with_analysis(tmp_path, contract, policy, request_spec)
    artifact = store.read(run_id, "validated_analysis.json")
    output = tmp_path / "authoritative-evidence"
    export_powerbi(run_id, store, output, request_spec)

    evidence = json.loads((output / "evidence.json").read_text(encoding="utf-8"))
    spec = json.loads((output / "bi_spec.json").read_text(encoding="utf-8"))
    model = json.loads(
        (output / "EvidenceBI.SemanticModel" / "model.bim").read_text(encoding="utf-8")
    )
    accepted = [
        item for item in artifact["findings"] if item["validation"]["accepted"] is True
    ]

    assert evidence["validated_analysis_fingerprint"] == artifact["content_fingerprint"]
    assert evidence["findings"] == accepted
    assert evidence["limitations"] == artifact["limitations"]
    assert evidence["root_scope"] == artifact["root_scope"]
    assert spec["analysis_artifact"]["fingerprint"] == artifact["content_fingerprint"]
    assert spec["analysis_artifact"]["accepted_finding_ids"] == artifact["accepted_finding_ids"]
    assert spec["analysis_artifact"]["limitations"] == artifact["limitations"]

    evidence_table = next(
        table for table in model["model"]["tables"] if table["name"] == "Evidence"
    )
    expression = evidence_table["partitions"][0]["source"]["expression"]
    rows = json.loads(base64.b64decode(expression[1].split('"')[1]))
    columns = [column["name"] for column in evidence_table["columns"]]
    assert [row[0] for row in rows] == [item["candidate"]["finding_id"] for item in accepted]
    evidence_index = columns.index("EvidenceID")
    scope_index = columns.index("ScopeJSON")
    label_index = columns.index("ScopeLabel")
    assert [row[evidence_index] for row in rows] == [
        item["candidate"]["evidence_id"] for item in accepted
    ]
    assert [json.loads(row[scope_index]) for row in rows] == [
        item["candidate"]["scope"] for item in accepted
    ]
    assert all(row[label_index] for row in rows)


def test_export_preserves_accepted_agent_drilldown_evidence(
    tmp_path, dataset, contract, request_spec
):
    class RootAndDrilldownAdapter:
        name = "export-drilldown-fixture"
        is_live = False

        def invoke(self, payload, *args):
            observations = payload["observations"]
            root_filters = payload["filters"]
            root_comparison = next(
                (
                    item
                    for item in observations
                    if item["tool"] == "compare_periods"
                    and item["scope"].get("filters", {}) == root_filters
                ),
                None,
            )
            root_dimensions = {
                item["scope"].get("dimension")
                for item in observations
                if item["tool"] == "breakdown_change"
                and item["scope"].get("filters", {}) == root_filters
            }
            if root_comparison is None:
                action = Action(kind="tool", tool="compare_periods", reason="Get root total.")
            elif "Region" not in root_dimensions:
                action = Action(
                    kind="tool", tool="breakdown_change", dimension="Region", reason="Get Region."
                )
            elif "Product" not in root_dimensions:
                action = Action(
                    kind="tool", tool="breakdown_change", dimension="Product", reason="Get Product."
                )
            elif not any(
                item["tool"] == "compare_periods"
                and item["scope"].get("filters", {}) != root_filters
                for item in observations
            ):
                region = next(
                    item
                    for item in observations
                    if item["tool"] == "breakdown_change"
                    and item["scope"].get("dimension") == "Region"
                    and item["scope"].get("filters", {}) == root_filters
                )
                token = region["data"]["groups"][0]["label"]
                action = Action(
                    kind="tool",
                    tool="compare_periods",
                    filters=[{"dimension": "Region", "values": [token]}],
                    reason="Check a narrowed Region drilldown.",
                )
            else:
                citations = [
                    item["evidence_id"]
                    for item in observations
                    if item["scope"].get("filters", {}) == root_filters
                ]
                action = Action(
                    kind="finish", reason="All root scopes and the drilldown were checked.",
                    evidence_ids=citations,
                )
            return ModelReply(action.model_dump_json())

    policy = cloud_policy(dataset)
    if "analysis" not in policy.approved_stages:
        policy.approved_stages.append("analysis")
    store = RunStore(tmp_path / "runtime")
    run_id = ingest_run(EXAMPLES / "sales.csv", contract, policy, store)
    report = AgentRunner(store, RootAndDrilldownAdapter()).run(run_id, request_spec)
    assert report["status"] == "COMPLETED"

    artifact = store.read(run_id, "validated_analysis.json")
    root_ids = set(artifact["root_evidence_ids"])
    accepted_drilldowns = [
        record
        for record in artifact["findings"]
        if record["validation"]["accepted"]
        and record["candidate"]["evidence_id"] not in root_ids
    ]
    assert accepted_drilldowns

    output = tmp_path / "agent-export"
    export_powerbi(run_id, store, output, request_spec)
    evidence = json.loads((output / "evidence.json").read_text(encoding="utf-8"))
    exported_ids = set(evidence["accepted_evidence_ids"])
    assert {
        record["candidate"]["evidence_id"] for record in accepted_drilldowns
    }.issubset(exported_ids)
    assert evidence["validated_analysis_fingerprint"] == artifact["content_fingerprint"]
    narrative_path = next(
        (output / "EvidenceBI.Report/definition/pages").glob(
            "*/visuals/6fcea0e5f701a94ad535/visual.json"
        )
    )
    narrative = json.loads(narrative_path.read_text(encoding="utf-8"))
    narrative_text = "\n".join(
        run["value"]
        for paragraph in narrative["visual"]["objects"]["general"][0]["properties"][
            "paragraphs"
        ]
        for run in paragraph["textRuns"]
    )
    assert all(
        record["candidate"]["text"] not in narrative_text
        for record in accepted_drilldowns
    )


def test_embedded_cells_cannot_inject_m_code(dataset, contract, request_spec):
    changed = dataset
    changed.frame.loc[0, "Region"] = '"; Web.Contents("https://evil.example.test")'
    engine = Analytics(changed, contract)
    model, _ = build_model(engine, request_spec)
    for table in model["model"]["tables"]:
        expression = "\n".join(table["partitions"][0]["source"]["expression"])
        assert "Web.Contents" not in expression
        assert "evil.example.test" not in expression


def test_null_context_fixture_matches_independent_expected(contract, request_spec):
    from bi_analyst.contracts import DataPolicy
    from bi_analyst.data import load_csv

    contract.metrics[0].null_policy = "exclude"
    engine = Analytics(load_csv(EXAMPLES / "null_sales.csv", DataPolicy()), contract)
    overall = engine.compare_periods(request_spec)["data"]
    assert overall["previous"]["amount_minor"] == 10
    assert overall["current"]["amount_minor"] is None
    north = request_spec.model_copy(update={"filters": {"Region": ["North"]}})
    values = engine.compare_periods(north)["data"]
    assert values["current"]["amount_minor"] == 0
    assert values["delta_minor"] == -10
    model, _ = build_model(engine, request_spec)
    assert len(model["model"]["tables"][0]["partitions"]) == 1


def test_case_distinct_labels_are_not_silently_merged_in_powerbi(dataset, contract, request_spec):
    import pytest

    from bi_analyst.errors import BIError

    dataset.frame.loc[0, "Region"] = "north"
    engine = Analytics(dataset, contract)
    assert len(engine.breakdown_change(request_spec, "Region")["data"]["groups"]) == 3
    with pytest.raises(BIError) as error:
        build_model(engine, request_spec)
    assert error.value.code == "PBI_LABEL_COLLISION"


def test_reserved_calendar_dimension_fails_before_model_generation(dataset, contract, request_spec):
    import pytest

    from bi_analyst.errors import BIError

    contract.dimensions["Date"] = "Region"
    request_spec.dimensions = ["Date"]
    with pytest.raises(BIError) as error:
        build_model(Analytics(dataset, contract), request_spec)
    assert error.value.code == "PBI_NAME_COLLISION"


def test_partial_export_has_no_completed_manifest(
    tmp_path, contract, policy, request_spec, monkeypatch
):
    import pytest

    import bi_analyst.bi as bi
    from bi_analyst.errors import BIError

    store = RunStore(tmp_path / "runtime")
    run_id = ingest_run(EXAMPLES / "sales.csv", contract, policy, store)
    analyze_deterministic(run_id, store, request_spec)
    original = bi.atomic_bytes

    def fail_notes(path, content):
        if path.name == "README.md":
            raise BIError("STORAGE_ERROR", "Synthetic disk failure.")
        original(path, content)

    monkeypatch.setattr(bi, "atomic_bytes", fail_notes)
    output = tmp_path / "partial"
    with pytest.raises(BIError):
        export_powerbi(run_id, store, output, request_spec)
    assert not (output / "export_manifest.json").exists()


def _t15_builder_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "build_demo.py"
    spec = importlib.util.spec_from_file_location("t15_demo_builder", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _embedded_table_rows(table):
    expression = table["partitions"][0]["source"]["expression"]
    encoded = expression[1].split('"')[1]
    return json.loads(base64.b64decode(encoded))


def _replace_embedded_table_rows(table, rows):
    expression = table["partitions"][0]["source"]["expression"]
    encoded = expression[1].split('"')[1]
    replacement = base64.b64encode(
        json.dumps(
            rows,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).decode()
    expression[1] = expression[1].replace(encoded, replacement)


@pytest.fixture(scope="module")
def dashboard_refresh_build(tmp_path_factory):
    builder = _t15_builder_module()
    root = Path(__file__).resolve().parents[1]
    work = tmp_path_factory.mktemp("dashboard-refresh-r1")
    output = work / "candidate"
    verification = work / "verification.json"
    result = builder.build(
        output,
        baseline=root / "deliverables/PowerBI_Demo_Candidate",
        verification_output=verification,
    )
    return builder, output, verification, result


def _t15_pre_t14_baseline(tmp_path):
    """Create a local pre-T14 baseline for legacy comparator tests."""
    root = Path(__file__).resolve().parents[1]
    baseline = tmp_path / "pre-t14-baseline"
    shutil.copytree(root / "deliverables/PowerBI_Demo_Candidate", baseline)
    model_path = baseline / "EvidenceBI.SemanticModel/model.bim"
    model = json.loads(model_path.read_text(encoding="utf-8"))
    evidence = next(table for table in model["model"]["tables"] if table["name"] == "Evidence")
    evidence["columns"] = [
        column for column in evidence["columns"] if column["name"] not in {"ScopeJSON", "ValidationJSON"}
    ]
    model_path.write_text(json.dumps(model), encoding="utf-8")
    return baseline


def test_t15_demo_dataset_is_seeded_versioned_and_keeps_source_schema():
    builder = _t15_builder_module()
    first = builder.generate_demo_rows(20260923)
    second = builder.generate_demo_rows(20260923)
    other_seed = builder.generate_demo_rows(7)

    assert first == second
    assert first != other_seed
    assert len(first) == 18
    assert set(first[0]) == set(builder.CSV_FIELDS)
    assert builder.GENERATOR_VERSION == "dashboard-refresh-r3"
    assert {(row["OrderDate"][:7]) for row in first} == {"2026-01", "2026-02"}
    assert len({(row["Region"], row["Product"]) for row in first}) == 9


def test_t15_independent_oracle_has_offsets_and_dominant_intersection():
    builder = _t15_builder_module()
    rows = builder.generate_demo_rows()
    oracle = builder.independent_oracle(rows)
    expected = {case["id"]: case["expected"] for case in oracle["cases"]}

    assert expected["root"]["Current"] - expected["root"]["Previous"] == 60_000
    assert expected["region_north"]["Change"] == 122_000
    assert expected["product_anchor"]["Change"] == 80_000
    assert expected["intersection_north_anchor"]["Change"] == 120_000
    assert expected["intersection_north_anchor"]["Change"] / expected["root"]["Change"] == 2
    date_context_expected = {
        "Previous": 943_363,
        "Current": 1_003_363,
        "Change": 60_000,
        "Growth": 0.0636022400708953,
    }
    for case_id, expected_base in (("date_january", 943_363), ("date_no_rows", None)):
        case = expected[case_id]
        assert case["Base"] == expected_base
        for field in ("Previous", "Current", "Change"):
            assert case[field] == date_context_expected[field]
        assert abs(Decimal(str(case["Growth"])) - Decimal(str(date_context_expected["Growth"]))) <= Decimal(
            str(oracle["growth_ratio_tolerance"])
        )
    assert expected["no_region_rows"] == {
        "Base": None,
        "Previous": 0,
        "Current": 0,
        "Change": 0,
        "Growth": None,
    }
    assert oracle["metric_tolerance"] == 0
    assert oracle["growth_ratio_tolerance"] == 1e-12


def test_t15_candidate_builder_rejects_any_output_overlapping_current():
    builder = _t15_builder_module()
    current = Path(__file__).resolve().parents[1] / "deliverables/PowerBI_Demo_Current"
    for output in (current, current / "nested", current.parent):
        with pytest.raises(ValueError, match="separate sibling tree"):
            builder.build(output)


def test_t15_independent_oracle_agrees_with_analytics_tools(tmp_path, contract, request_spec, policy):
    builder = _t15_builder_module()
    rows = builder.generate_demo_rows()
    source = tmp_path / "seeded_demo.csv"
    source.write_bytes(builder.serialize_demo_csv(rows))
    engine = Analytics(load_csv(source, policy), contract)
    oracle = {case["id"]: case["expected"] for case in builder.independent_oracle(rows)["cases"]}
    contexts = {
        "root": {},
        "region_north": {"Region": ["North"]},
        "product_anchor": {"Product": ["Anchor"]},
        "intersection_north_anchor": {"Region": ["North"], "Product": ["Anchor"]},
        "no_region_rows": {"Region": ["Atlantis"]},
    }
    for case_id, filters in contexts.items():
        request = request_spec.model_copy(update={"filters": filters})
        actual = engine.compare_periods(request)["data"]
        expected = oracle[case_id]
        assert actual["previous"]["amount_minor"] == expected["Previous"]
        assert actual["current"]["amount_minor"] == expected["Current"]
        assert actual["delta_minor"] == expected["Change"]
        if expected["Growth"] is None:
            assert actual["growth_pct"] is None
        else:
            actual_ratio = Decimal(actual["growth_pct"]) / Decimal(100)
            assert abs(actual_ratio - Decimal(str(expected["Growth"]))) <= Decimal("1e-12")

    for dimension, source_column in (("Region", "Region"), ("Product", "Product")):
        actual_groups = {
            group["label"]: group["delta_minor"]
            for group in engine.breakdown_change(request_spec, dimension)["data"]["groups"]
        }
        direct_groups = {}
        for label in {row[source_column] for row in rows}:
            previous = sum(
                int(row["Revenue"])
                for row in rows
                if row[source_column] == label and row["OrderDate"].startswith("2026-01")
            )
            current = sum(
                int(row["Revenue"])
                for row in rows
                if row[source_column] == label and row["OrderDate"].startswith("2026-02")
            )
            direct_groups[label] = current - previous
        assert actual_groups == direct_groups


@pytest.mark.parametrize(
    "mutation",
    ["old_column_type", "old_column_order", "addition_type", "missing_addition"],
)
def test_t15_static_parity_rejects_evidence_schema_drift(tmp_path, mutation):
    builder = _t15_builder_module()
    baseline = _t15_pre_t14_baseline(tmp_path)
    root = Path(__file__).resolve().parents[1]
    frozen_candidate = root / "deliverables/PowerBI_Demo_Candidate"
    candidate = tmp_path / mutation
    shutil.copytree(frozen_candidate, candidate)

    model_path = candidate / "EvidenceBI.SemanticModel/model.bim"
    model = json.loads(model_path.read_text(encoding="utf-8"))
    columns = next(table["columns"] for table in model["model"]["tables"] if table["name"] == "Evidence")
    if mutation == "old_column_type":
        next(column for column in columns if column["name"] == "FindingID")["dataType"] = "int64"
    elif mutation == "old_column_order":
        columns[0], columns[1] = columns[1], columns[0]
    elif mutation == "addition_type":
        next(column for column in columns if column["name"] == "ScopeJSON")["dataType"] = "int64"
    else:
        columns[:] = [column for column in columns if column["name"] != "ScopeJSON"]
    model_path.write_text(json.dumps(model), encoding="utf-8")

    result = builder.compare_powerbi_projects(baseline, candidate)
    assert result["failures"], f"static parity accepted Evidence mutation: {mutation}"


def test_t15_post_t14_exact_parity_self_passes_and_layout_mutation_fails(tmp_path):
    builder = _t15_builder_module()
    root = Path(__file__).resolve().parents[1]
    baseline = root / "deliverables/PowerBI_Demo_Candidate"

    self_parity = builder.compare_powerbi_projects_exact(baseline, baseline)
    assert not self_parity["failures"], self_parity["failures"]

    mutated = tmp_path / "mutated-post-t14"
    shutil.copytree(baseline, mutated)
    visual_path = next((mutated / "EvidenceBI.Report/definition/pages").glob("*/visuals/*/visual.json"))
    visual = json.loads(visual_path.read_text(encoding="utf-8"))
    visual["position"]["x"] += 1
    visual_path.write_text(json.dumps(visual), encoding="utf-8")

    mutation_result = builder.compare_powerbi_projects_exact(baseline, mutated)
    assert mutation_result["failures"], "exact post-T14 parity accepted a layout mutation"


def test_t15_builder_guards_baseline_verification_and_cli_defaults(tmp_path):
    builder = _t15_builder_module()
    with pytest.raises(FileNotFoundError, match="tracked Power BI baseline"):
        builder.build(
            tmp_path / "candidate",
            baseline=tmp_path / "missing-baseline",
        )
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "candidate"
    baseline = root / "deliverables/PowerBI_Demo_Candidate"
    current = root / "deliverables/PowerBI_Demo_Current"
    for verification in (
        baseline / "EvidenceBI.SemanticModel/model.bim",
        current / "EvidenceBI.Report/definition.pbir",
        output / "EvidenceBI.SemanticModel/model.bim",
    ):
        with pytest.raises(ValueError, match="verification output"):
            builder.build(
                output,
                verification_output=verification,
            )

    args = builder.build_argument_parser().parse_args([])

    assert args.output == builder.DEFAULT_OUTPUT
    assert args.output != baseline
    assert baseline not in args.output.parents
    assert args.output not in baseline.parents


def test_t15_builder_builds_to_fresh_output_with_external_verification(
    dashboard_refresh_build,
):
    _builder, _output, verification, result = dashboard_refresh_build
    assert result["analysis_status"] == "COMPLETED"
    assert result["verification"] == (
        "static schema, references, and dashboard-refresh allowlist passed"
    )
    assert verification.is_file()


def test_dashboard_refresh_manifest_ids_layout_bindings_and_model_allowlist(
    dashboard_refresh_build,
):
    builder, output, verification, _result = dashboard_refresh_build
    root = Path(__file__).resolve().parents[1]
    baseline = root / "deliverables/PowerBI_Demo_Candidate"
    manifest = json.loads(builder.LAYOUT_MANIFEST.read_text(encoding="utf-8"))
    check = builder.compare_powerbi_projects_refresh(
        baseline,
        output,
        layout_manifest=builder.LAYOUT_MANIFEST,
    )
    record = json.loads(verification.read_text(encoding="utf-8"))

    assert not check["failures"], check["failures"]
    assert check["pages"] == 2
    assert check["data_visuals"] == 9
    assert check["text_objects"] == 4
    assert check["interaction_status"] == "not_checked"
    assert record["pbir_refresh_allowlist"] == "passed"
    assert record["execution"] == record["reconciliation"] == "not_checked"
    assert record["interactions"] == record["rendering"] == "not_checked"

    expected_page_order = [page["id"] for page in manifest["pages"]]
    pages = json.loads(
        (output / "EvidenceBI.Report/definition/pages/pages.json").read_text(
            encoding="utf-8"
        )
    )
    assert pages["pageOrder"] == expected_page_order

    old_model = json.loads(
        (baseline / "EvidenceBI.SemanticModel/model.bim").read_text(encoding="utf-8")
    )["model"]
    new_model = json.loads(
        (output / "EvidenceBI.SemanticModel/model.bim").read_text(encoding="utf-8")
    )["model"]
    assert new_model["relationships"] == old_model["relationships"]
    old_measures = next(
        table["measures"] for table in old_model["tables"] if table["name"] == "FactSales"
    )
    new_measures = next(
        table["measures"] for table in new_model["tables"] if table["name"] == "FactSales"
    )
    assert new_measures == old_measures

    old_shapes = {
        table["name"]: [(column["name"], column["dataType"]) for column in table["columns"]]
        for table in old_model["tables"]
    }
    new_shapes = {
        table["name"]: [(column["name"], column["dataType"]) for column in table["columns"]]
        for table in new_model["tables"]
    }
    assert set(old_shapes) == set(new_shapes)
    for table_name in old_shapes:
        if table_name == "Evidence":
            assert [item for item in new_shapes[table_name] if item[0] != "ScopeLabel"] == (
                old_shapes[table_name]
            )

            assert [item for item in new_shapes[table_name] if item[0] == "ScopeLabel"] == [
                ("ScopeLabel", "string")
            ]
        else:
            assert new_shapes[table_name] == old_shapes[table_name]

    old_analysis_info = next(
        table for table in old_model["tables"] if table["name"] == "AnalysisInfo"
    )
    new_analysis_info = next(
        table for table in new_model["tables"] if table["name"] == "AnalysisInfo"
    )
    old_info_rows = _embedded_table_rows(old_analysis_info)
    new_info_rows = _embedded_table_rows(new_analysis_info)
    old_info = dict(old_info_rows)
    new_info = dict(new_info_rows)
    assert [row[0] for row in new_info_rows] == [row[0] for row in old_info_rows]
    assert {
        key: value
        for key, value in new_info.items()
        if key != "Validated analysis fingerprint"
    } == {
        key: value
        for key, value in old_info.items()
        if key != "Validated analysis fingerprint"
    }
    fingerprint_value = new_info["Validated analysis fingerprint"]
    evidence = json.loads((output / "evidence.json").read_text(encoding="utf-8"))
    export_manifest = json.loads(
        (output / "export_manifest.json").read_text(encoding="utf-8")
    )
    bi_spec = json.loads((output / "bi_spec.json").read_text(encoding="utf-8"))
    business_case = json.loads(
        (output / "business_case_summary.json").read_text(encoding="utf-8")
    )
    assert fingerprint_value != old_info["Validated analysis fingerprint"]
    assert fingerprint_value == evidence["validated_analysis_fingerprint"]
    assert fingerprint_value == export_manifest["validated_analysis_fingerprint"]
    assert fingerprint_value == bi_spec["analysis_artifact"]["fingerprint"]
    assert fingerprint_value == business_case["analysis_artifact_fingerprint"]


@pytest.mark.parametrize(
    "mutation",
    [
        "empty",
        "missing",
        "missing_pair",
        "unknown_source",
        "unknown_target",
        "self_pair",
        "wrong_type",
        "duplicate",
        "conflicting_duplicate",
    ],
)
def test_dashboard_refresh_comparator_rejects_invalid_interaction_contract(
    tmp_path, dashboard_refresh_build, mutation
):
    builder, frozen, _verification, _result = dashboard_refresh_build
    candidate = tmp_path / mutation
    shutil.copytree(frozen, candidate)
    page_path = candidate / "EvidenceBI.Report/definition/pages/35829699879dfc38c755/page.json"
    page = json.loads(page_path.read_text(encoding="utf-8"))
    interactions = page["visualInteractions"]
    if mutation == "empty":
        page["visualInteractions"] = []
    elif mutation == "missing":
        del page["visualInteractions"]
    elif mutation == "missing_pair":
        page["visualInteractions"] = interactions[:-1]
    elif mutation == "unknown_source":
        page["visualInteractions"] = interactions + [
            {"source": "unknown-source", "target": interactions[0]["target"], "type": "NoFilter"}
        ]
    elif mutation == "unknown_target":
        page["visualInteractions"] = interactions + [
            {"source": interactions[0]["source"], "target": "unknown-target", "type": "NoFilter"}
        ]
    elif mutation == "self_pair":
        page["visualInteractions"] = interactions + [
            {"source": interactions[0]["source"], "target": interactions[0]["source"], "type": "NoFilter"}
        ]
    elif mutation == "wrong_type":
        page["visualInteractions"] = [dict(interactions[0], type="Filter")] + interactions[1:]
    else:
        duplicate = dict(interactions[0])
        if mutation == "conflicting_duplicate":
            duplicate["type"] = "Filter"
        page["visualInteractions"] = interactions + [duplicate]
    page_path.write_text(json.dumps(page), encoding="utf-8")

    result = builder.compare_powerbi_projects_refresh(
        Path(__file__).resolve().parents[1] / "deliverables/PowerBI_Demo_Candidate",
        candidate,
        layout_manifest=builder.LAYOUT_MANIFEST,
    )
    assert any("visualInteractions" in failure for failure in result["failures"])


def test_interaction_contract_accepts_positive_one_dimension_map():
    sources = {"source-a", "source-b"}
    targets = {"target-1", "target-2", "target-3", "target-4", "target-5", "target-6"}
    interactions = [
        {"source": source, "target": target, "type": "NoFilter"}
        for source in sorted(sources)
        for target in sorted(targets)
    ]
    assert len(interactions) == 12
    assert _interaction_contract_failures(interactions, sources, targets, "NoFilter") == []


def test_dashboard_refresh_allowlists_explicit_no_filter_visual_behavior(
    tmp_path, dashboard_refresh_build
):
    builder, frozen, _verification, _result = dashboard_refresh_build
    candidate = tmp_path / "drill-filter-mutation"
    shutil.copytree(frozen, candidate)
    visual_path = next(
        (candidate / "EvidenceBI.Report/definition/pages").glob("*/visuals/*/visual.json")
    )
    document = json.loads(visual_path.read_text(encoding="utf-8"))
    document["visual"]["drillFilterOtherVisuals"] = True
    visual_path.write_text(json.dumps(document), encoding="utf-8")

    result = builder.compare_powerbi_projects_refresh(
        Path(__file__).resolve().parents[1] / "deliverables/PowerBI_Demo_Candidate",
        candidate,
        layout_manifest=builder.LAYOUT_MANIFEST,
    )
    assert any("does not disable drill interaction" in failure for failure in result["failures"])


def test_build_report_disables_drill_filtering_for_no_filter_interactions(request_spec):
    documents = build_report(request_spec)
    visuals = [
        document["visual"]
        for path, document in documents.items()
        if "/visuals/" in path and path.endswith("/visual.json")
    ]

    assert visuals
    assert all(
        visual["drillFilterOtherVisuals"] is False for visual in visuals
    )


def test_build_report_uses_signed_bar_colors_and_hides_scope_metadata(request_spec):
    documents = build_report(request_spec)
    visuals = [
        document["visual"]
        for path, document in documents.items()
        if "/visuals/" in path and path.endswith("/visual.json")
    ]

    bars = [visual for visual in visuals if visual["visualType"] == "barChart"]
    assert len(bars) == 2
    for bar in bars:
        fill_rule = bar["objects"]["dataPoint"][0]["properties"]["fill"]["solid"][
            "color"
        ]["expr"]["FillRule"]
        assert fill_rule["Input"]["Measure"]["Expression"]["SourceRef"]["Entity"] == (
            "FactSales"
        )
        gradient = fill_rule["FillRule"]["linearGradient3"]
        assert gradient["min"]["color"]["Literal"]["Value"] == "'#B54734'"
        assert gradient["mid"]["color"]["Literal"]["Value"] == "'#64748B'"
        assert gradient["max"]["color"]["Literal"]["Value"] == "'#087F72'"
        assert gradient["mid"]["value"]["Literal"]["Value"] == "0D"
        assert bar["objects"]["dataPoint"][0]["selector"] == {
            "data": [{"dataViewWildcard": {"matchingOption": 0}}]
        }

    scope_document = next(
        document
        for path, document in documents.items()
        if "/visuals/" in path
        and path.endswith("/visual.json")
        and document["visual"]
        .get("query", {})
        .get("queryState", {})
        .get("Values", {})
        .get("projections", [{}])[0]
        .get("queryRef")
        == "AnalysisInfo.Property"
    )
    scope_filter = scope_document["filterConfig"]["filters"][0]
    assert scope_filter["type"] == "Categorical"
    assert scope_filter["isHiddenInViewMode"] is True
    where = scope_filter["filter"]["Where"][0]["Condition"]["Not"]["Expression"]["In"]
    excluded = {
        item[0]["Literal"]["Value"]
        for item in where["Values"]
    }
    assert excluded == {
        "'Dataset'",
        "'Validated analysis fingerprint'",
        "'Root analysis scope'",
    }
    inverted_selection = (
        scope_filter["objects"]["general"][0]["properties"]
        ["isInvertedSelectionMode"]["expr"]["Literal"]["Value"]
    )
    assert inverted_selection == "true"


def test_dashboard_refresh_native_reference_structures_and_growth_format(
    dashboard_refresh_build,
):
    _builder, output, _verification, _result = dashboard_refresh_build
    manifest = json.loads(_builder.LAYOUT_MANIFEST.read_text(encoding="utf-8"))
    objects = {
        item["key"]: item for page in manifest["pages"] for item in page["objects"]
    }

    def visual(key):
        item = objects[key]
        return json.loads(
            next(
                (output / "EvidenceBI.Report/definition/pages").glob(
                    f"*/visuals/{item['id']}/visual.json"
                )
            ).read_text(encoding="utf-8")
        )

    trend = visual("C03")["visual"]
    assert trend["visualType"] == "columnChart"
    assert set(trend["query"]["queryState"]) == {"Category", "Y"}
    assert (
        trend["visualContainerObjects"]["title"][0]["properties"]["text"]["expr"][
            "Literal"
        ]["Value"]
        == "'Doanh thu quan sát theo tháng'"
    )
    for key in ("T01", "T02", "T03", "T04"):
        textbox = visual(key)["visual"]
        assert textbox["visualType"] == "textbox"
        assert "query" not in textbox
        paragraphs = textbox["objects"]["general"][0]["properties"]["paragraphs"]
        assert paragraphs and all(paragraph["textRuns"] for paragraph in paragraphs)

    growth = visual("K04")["visual"]
    growth_projection = growth["query"]["queryState"]["Data"]["projections"][0]
    assert growth_projection["format"] == "+0.00%;-0.00%;0.00%"
    value = growth["objects"]["value"][0]
    assert value["selector"] == {"id": "default"}
    custom_format = value["properties"]["customFormatString"]["expr"]["Literal"][
        "Value"
    ]
    assert custom_format == "'+0.00%;-0.00%;0.00%'"
    assert _format_pattern(0, signed=True) == "+#,0;-#,0;#,0"

    change = visual("K03")["visual"]
    assert change["query"]["queryState"]["Data"]["projections"][0]["format"] == (
        "+#,0;-#,0;#,0"
    )
    for key in ("C01", "C02"):
        bar = visual(key)["visual"]
        assert bar["query"]["queryState"]["Y"]["projections"][0]["format"] == (
            "+#,0;-#,0;#,0"
        )

    # Verify R2 table wordWrap
    findings = visual("E01")["visual"]
    assert findings["objects"]["columnHeaders"][0]["properties"]["wordWrap"]["expr"]["Literal"]["Value"] == "true"
    assert findings["objects"]["values"][0]["properties"]["wordWrap"]["expr"]["Literal"]["Value"] == "true"

    # Verify R2 overview interaction isolation
    overview_page = json.loads(
        (output / "EvidenceBI.Report/definition/pages/35829699879dfc38c755/page.json").read_text(
            encoding="utf-8"
        )
    )
    assert "visualInteractions" in overview_page
    assert all(item["type"] == "NoFilter" for item in overview_page["visualInteractions"])



def test_scope_label_preserves_root_narrowed_filters_null_empty_and_order():
    previous = Period(start="2026-01-01", end="2026-02-01")
    current = Period(start="2026-02-01", end="2026-03-01")
    root_group = AnalysisScope(
        metric_id="Revenue",
        previous=previous,
        current=current,
        filters={},
        unit="VND",
        scale=0,
        dimension="Region",
    )
    narrowed_group = root_group.model_copy(update={"filters": {"Product": ["Anchor"]}})
    records = [
        (narrowed_group, "North"),
        (root_group, "North"),
    ]
    rendered = [_scope_label(scope, group_label=label) for scope, label in records]

    assert "Nhóm: Region = North" in rendered[0] and "Nhóm: Region = North" in rendered[1]
    assert "Product = Anchor" in rendered[0]
    assert "Product = Anchor" not in rendered[1]
    assert rendered == [
        _scope_label(narrowed_group, group_label="North"),
        _scope_label(root_group, group_label="North"),
    ]

    special = root_group.model_copy(update={"filters": {"Product": [None, ""]}})
    null_group = _scope_label(special, group_label=None)
    empty_group = _scope_label(special, group_label="")
    assert "Product = (Thiếu giá trị), (Chuỗi rỗng)" in null_group
    assert "Nhóm: Region = (Thiếu giá trị)" in null_group
    assert "Nhóm: Region = (Chuỗi rỗng)" in empty_group
    assert null_group != empty_group


@pytest.mark.parametrize(
    "mutation",
    [
        "scope_label",
        "e01_binding",
        "overlap",
        "schema",
        "visual_id",
        "finding_source_column",
        "evidence_m",
        "analysis_info_m",
        "analysis_info_rows",
        "analysis_info_fingerprint",
        "culture",
        "scope_filter",
    ],
)
def test_dashboard_refresh_comparator_rejects_non_allowlisted_mutations(
    tmp_path,
    dashboard_refresh_build,
    mutation,
):
    builder, frozen, _verification, _result = dashboard_refresh_build
    root = Path(__file__).resolve().parents[1]
    candidate = tmp_path / mutation
    shutil.copytree(frozen, candidate)
    manifest = json.loads(builder.LAYOUT_MANIFEST.read_text(encoding="utf-8"))
    objects = {
        item["key"]: item for page in manifest["pages"] for item in page["objects"]
    }

    model_mutations = {
        "scope_label",
        "schema",
        "finding_source_column",
        "evidence_m",
        "analysis_info_m",
        "analysis_info_rows",
        "analysis_info_fingerprint",
        "culture",
    }
    if mutation in model_mutations:
        model_path = candidate / "EvidenceBI.SemanticModel/model.bim"
        model = json.loads(model_path.read_text(encoding="utf-8"))
        evidence = next(table for table in model["model"]["tables"] if table["name"] == "Evidence")
        columns = evidence["columns"]
        scope_index = next(
            index for index, column in enumerate(columns) if column["name"] == "ScopeLabel"
        )
        if mutation == "schema":
            columns[scope_index]["dataType"] = "int64"
        elif mutation == "scope_label":
            expression = evidence["partitions"][0]["source"]["expression"]
            encoded = expression[1].split('"')[1]
            rows = json.loads(base64.b64decode(encoded))
            rows[0][scope_index] = "wrong scope"
            replacement = base64.b64encode(
                json.dumps(
                    rows,
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).decode()
            expression[1] = expression[1].replace(encoded, replacement)
        elif mutation == "finding_source_column":
            next(column for column in columns if column["name"] == "Finding")[
                "sourceColumn"
            ] = "FindingMutated"
        elif mutation == "evidence_m":
            evidence["partitions"][0]["source"]["expression"][-1] = (
                "    Table.FirstN(Typed,0)"
            )
        elif mutation in {
            "analysis_info_m",
            "analysis_info_rows",
            "analysis_info_fingerprint",
        }:
            analysis_info = next(
                table
                for table in model["model"]["tables"]
                if table["name"] == "AnalysisInfo"
            )
            expression = analysis_info["partitions"][0]["source"]["expression"]
            if mutation == "analysis_info_m":
                expression[-1] = "    Table.FirstN(Typed,0)"
            else:
                rows = _embedded_table_rows(analysis_info)
                if mutation == "analysis_info_rows":
                    rows[0][1] = "mutated dataset identity"
                else:
                    baseline_model = json.loads(
                        (
                            root
                            / "deliverables/PowerBI_Demo_Candidate/EvidenceBI.SemanticModel/model.bim"
                        ).read_text(encoding="utf-8")
                    )
                    baseline_info = next(
                        table
                        for table in baseline_model["model"]["tables"]
                        if table["name"] == "AnalysisInfo"
                    )
                    stale_fingerprint = dict(_embedded_table_rows(baseline_info))[
                        "Validated analysis fingerprint"
                    ]
                    next(
                        row
                        for row in rows
                        if row[0] == "Validated analysis fingerprint"
                    )[1] = stale_fingerprint
                _replace_embedded_table_rows(analysis_info, rows)
        else:
            model["model"]["culture"] = "vi-VN"
        model_path.write_text(json.dumps(model), encoding="utf-8")
    else:
        key = "E01" if mutation == "e01_binding" else "S01" if mutation == "scope_filter" else "T02"
        item = objects[key]
        visual_path = next(
            (candidate / "EvidenceBI.Report/definition/pages").glob(
                f"*/visuals/{item['id']}/visual.json"
            )
        )
        visual = json.loads(visual_path.read_text(encoding="utf-8"))
        if mutation == "e01_binding":
            projection = visual["visual"]["query"]["queryState"]["Values"]["projections"][2]
            projection["field"]["Column"]["Property"] = "EvidenceID"
            projection["queryRef"] = "Evidence.EvidenceID"
            projection["nativeQueryRef"] = "EvidenceID"
        elif mutation == "overlap":
            visual["position"]["x"] = 400
        elif mutation == "scope_filter":
            del visual["filterConfig"]["filters"][0]["objects"]
        else:
            visual["name"] = "0" * 20
        visual_path.write_text(json.dumps(visual), encoding="utf-8")

    result = builder.compare_powerbi_projects_refresh(
        root / "deliverables/PowerBI_Demo_Candidate",
        candidate,
        layout_manifest=builder.LAYOUT_MANIFEST,
    )
    assert result["failures"], f"refresh comparator accepted mutation {mutation}"


def test_t15_duplicate_semantic_table_names_fail_references_and_parity(tmp_path):
    builder = _t15_builder_module()
    root = Path(__file__).resolve().parents[1]
    baseline = _t15_pre_t14_baseline(tmp_path)
    frozen_candidate = root / "deliverables/PowerBI_Demo_Candidate"
    candidate = tmp_path / "duplicate-evidence-table"
    shutil.copytree(frozen_candidate, candidate)

    model_path = candidate / "EvidenceBI.SemanticModel/model.bim"
    model = json.loads(model_path.read_text(encoding="utf-8"))
    evidence = next(table for table in model["model"]["tables"] if table["name"] == "Evidence")
    model["model"]["tables"].append(json.loads(json.dumps(evidence)))
    model_path.write_text(json.dumps(model), encoding="utf-8")

    references = builder.validate_references(candidate)
    parity = builder.compare_powerbi_projects(baseline, candidate)
    assert references["failures"] and parity["failures"], (
        "duplicate semantic table name was accepted: "
        f"references={references['failures']}, parity={parity['failures']}"
    )
