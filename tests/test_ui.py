import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from bi_analyst import provider as provider_module
from bi_analyst import ui as ui_module
from bi_analyst.analytics import Analytics
from bi_analyst.contracts import AnalysisRequest, DataPolicy
from bi_analyst.errors import BIError
from bi_analyst.store import RunStore
from bi_analyst.ui import (
    _accepted_findings,
    _analysis_status_presentation,
    _breakdown_presentation,
    _can_export_report,
    _downloadable_artifact,
    _evidence_sections,
    _export_unavailable_message,
    _format_money,
    _format_percent,
    _kpi_presentation,
    _render_plain_text,
    _root_comparison_result,
    _scope_label,
    _suggested_column_index,
    _validated_artifact,
    _validation_issue_presentation,
)

APP = Path(__file__).resolve().parents[1] / "app.py"


def _button(app, label):
    return next(item for item in app.button if item.label == label)


def _checkbox(app, label):
    return next(item for item in app.checkbox if item.label == label)


def test_missing_semantic_suggestion_does_not_default_to_first_column():
    columns = ["CustomerID", "Anything"]

    assert _suggested_column_index(columns, None) is None
    assert _suggested_column_index(columns, "Unmapped") is None
    assert _suggested_column_index(columns, "Anything") == 1


def test_root_kpi_ignores_an_earlier_narrowed_comparison():
    narrow = {
        "evidence_id": "EV_NARROW",
        "tool": "compare_periods",
        "scope": {"dimension": None, "filters": {"Region": ["North"]}},
        "data": {"previous": {"amount": 300}, "current": {"amount": 150}, "delta": -150},
    }
    root = {
        "evidence_id": "EV_ROOT",
        "tool": "compare_periods",
        "scope": {"dimension": None, "filters": {}},
        "data": {"previous": {"amount": 1000}, "current": {"amount": 600}, "delta": -400},
    }

    artifact = SimpleNamespace(
        root_evidence_ids=["EV_ROOT"],
        evidence_registry={"narrow": narrow, "root": root},
    )
    assert _root_comparison_result(artifact) == root
    assert _root_comparison_result(None) is None


def test_root_breakdowns_follow_requested_dimensions_and_narrowed_scope_stays_separate():
    narrowed = {
        "evidence_id": "EV_NARROW",
        "tool": "breakdown_change",
        "scope": {
            "metric_id": "Revenue",
            "unit": "VND",
            "scale": 0,
            "previous": {"start": "2026-01-01", "end": "2026-02-01"},
            "current": {"start": "2026-02-01", "end": "2026-03-01"},
            "filters": {"Product": ["Anchor"]},
            "dimension": "Region",
        },
        "data": {"groups": []},
    }
    product = {
        "evidence_id": "EV_PRODUCT",
        "tool": "breakdown_change",
        "scope": {"dimension": "Product", "filters": {}},
        "data": {"groups": []},
    }
    region = {
        "evidence_id": "EV_REGION",
        "tool": "breakdown_change",
        "scope": {"dimension": "Region", "filters": {}},
        "data": {"groups": []},
    }
    artifact = SimpleNamespace(
        root_evidence_ids=["EV_PRODUCT", "EV_REGION"],
        root_request=SimpleNamespace(dimensions=["Region", "Product"]),
        evidence_registry={
            "EV_NARROW": narrowed,
            "EV_PRODUCT": product,
            "EV_REGION": region,
        },
    )

    root, narrowed_records = _evidence_sections(artifact)

    assert [item["evidence_id"] for item in root] == ["EV_REGION", "EV_PRODUCT"]
    assert [item["evidence_id"] for item in narrowed_records] == ["EV_NARROW"]
    narrowed_label = _scope_label(narrowed_records[0]["scope"])
    assert "Product = Anchor" in narrowed_label
    assert "Chiều phân tích: Region" in narrowed_label
    assert "[2026-01-01, 2026-02-01)" in narrowed_label
    assert "Phạm vi phân tích" in narrowed_label
    assert "Phạm vi gốc" not in narrowed_label


def test_ui_findings_are_only_accepted_findings_from_validated_report():
    accepted = SimpleNamespace(validation=SimpleNamespace(accepted=True))
    rejected = SimpleNamespace(validation=SimpleNamespace(accepted=False))
    artifact = SimpleNamespace(findings=[accepted, rejected])

    assert _accepted_findings(artifact) == [accepted]
    assert _accepted_findings(None) == []


def test_business_formats_preserve_unavailable_zero_negative_and_currency_scale():
    assert _format_money(None, unit="VND", scale=0) == "Chưa đủ dữ liệu"
    assert _format_money("0", unit="VND", scale=0, signed=True) == "0 VND"
    assert _format_money("-1234.5", unit="USD", scale=2, signed=True) == "−1.234,50 USD"
    assert _format_money("1234", unit="VND", scale=0, signed=True) == "+1.234 VND"
    assert _format_percent(None, signed=True) == "Chưa đủ dữ liệu"
    assert _format_percent("0", signed=True) == "0,00%"
    assert _format_percent("-40", signed=True) == "−40,00%"
    assert _format_percent("125.555", signed=True) == "+125,56%"


def test_kpis_do_not_turn_unavailable_buckets_into_zero():
    evidence = {
        "scope": {"unit": "VND", "scale": 0},
        "data": {
            "previous": {"amount": "0", "status": "observed"},
            "current": {"amount": "999", "status": "unavailable"},
            "delta": None,
            "growth_pct": None,
        },
    }

    assert dict(_kpi_presentation(evidence)) == {
        "Kỳ trước": "0 VND",
        "Kỳ hiện tại": "Chưa đủ dữ liệu",
        "Chênh lệch": "Chưa đủ dữ liệu",
        "Tăng trưởng": "Chưa đủ dữ liệu",
    }


def test_real_analytics_known_zero_is_visible_in_kpis_and_breakdown(
    dataset, contract, request_spec
):
    engine = Analytics(dataset, contract)
    empty_periods = AnalysisRequest.model_validate(
        request_spec.model_dump(mode="json")
        | {
            "previous": {"start": "2026-01-01", "end": "2026-01-03"},
            "current": {"start": "2026-01-03", "end": "2026-01-05"},
        }
    )
    comparison = engine.compare_periods(empty_periods)

    assert comparison["data"]["previous"]["status"] == "known_zero"
    assert comparison["data"]["current"]["status"] == "known_zero"
    assert comparison["data"]["previous"]["coverage_confirmed"] is True
    assert dict(_kpi_presentation(comparison)) == {
        "Kỳ trước": "0 VND",
        "Kỳ hiện tại": "0 VND",
        "Chênh lệch": "0 VND",
        "Tăng trưởng": "Chưa đủ dữ liệu",
    }

    crossing_periods = AnalysisRequest.model_validate(
        request_spec.model_dump(mode="json")
        | {
            "previous": {"start": "2026-01-01", "end": "2026-01-11"},
            "current": {"start": "2026-01-11", "end": "2026-01-21"},
        }
    )
    evidence = engine.breakdown_change(crossing_periods, "Region")
    source_rows = {row["label"]: row for row in evidence["data"]["groups"]}
    table, chart = _breakdown_presentation(evidence)
    displayed = table.set_index("Nhóm")

    assert source_rows["North"]["current_status"] == "known_zero"
    assert source_rows["North"]["current_coverage_confirmed"] is True
    assert source_rows["South"]["previous_status"] == "known_zero"
    assert displayed.loc["North", "Kỳ hiện tại"] == "0 VND"
    assert displayed.loc["North", "Chênh lệch"] == "−300 VND"
    assert displayed.loc["North", "Đóng góp vào biến động ròng (%)"] == "−75,00%"
    assert displayed.loc["South", "Kỳ trước"] == "0 VND"
    assert displayed.loc["South", "Chênh lệch"] == "+700 VND"
    assert displayed.loc["South", "Đóng góp vào biến động ròng (%)"] == "+175,00%"
    assert set(chart["Nhóm"]) == {"North", "South"}

def test_breakdown_plain_labels_are_complete_and_keep_zero_denominator_unavailable():
    long_label = "<script>alert('x')</script> " + "N" * 180
    evidence = {
        "scope": {"unit": "VND", "scale": 0},
        "data": {
            "contribution_null_reason": "OVERALL_DELTA_ZERO",
            "groups": [
                {
                    "label": long_label,
                    "previous": "100",
                    "current": "50",
                    "delta": "-50",
                    "net_contribution_pct": "100",
                },
                {
                    "label": None,
                    "previous": None,
                    "current": None,
                    "delta": "50",
                    "net_contribution_pct": "-100",
                },
            ],
        },
    }

    table, chart = _breakdown_presentation(evidence)

    assert table.iloc[0]["Nhóm"].startswith("<script>")
    assert "N" * 180 in table.iloc[0]["Nhóm"]
    assert table.iloc[1]["Nhóm"] == "(Thiếu giá trị)"
    assert list(table["Đóng góp vào biến động ròng (%)"]) == [
        "Chưa đủ dữ liệu",
        "Chưa đủ dữ liệu",
    ]
    assert list(table["Kỳ trước"]) == ["100 VND", "Chưa đủ dữ liệu"]
    assert list(table["Kỳ hiện tại"]) == ["50 VND", "Chưa đủ dữ liệu"]
    assert list(table["Chênh lệch"]) == ["−50 VND", "Chưa đủ dữ liệu"]
    assert list(chart["Chênh lệch"]) == [-50.0]


def test_scope_plain_label_preserves_visible_text_and_distinguishes_null_from_empty():
    label = _scope_label(
        {
            "metric_id": "Revenue<script>",
            "unit": "VND",
            "scale": 0,
            "previous": {"start": "2026-01-01", "end": "2026-02-01"},
            "current": {"start": "2026-02-01", "end": "2026-03-01"},
            "filters": {"Region<img>": [None, "", "North&South"]},
            "dimension": "Product<b>",
        },
        group_label="Anchor<iframe>",
        has_group=True,
    )

    assert "Revenue<script>" in label
    assert "Region<img> = (Thiếu giá trị), (Chuỗi rỗng), North&South" in label
    assert "Nhóm: Product<b> = Anchor<iframe>" in label


def test_special_labels_use_plain_text_without_markdown_link_or_emphasis(monkeypatch):
    labels = ["North & South <Retail>", "[North](https://example.com) **retail**"]
    rendered = []

    monkeypatch.setattr(ui_module.st, "text", rendered.append)
    monkeypatch.setattr(
        ui_module.st,
        "markdown",
        lambda *args, **kwargs: pytest.fail("Dynamic labels must not use Markdown"),
    )

    for label in labels:
        _render_plain_text(label)

    table, chart = _breakdown_presentation(
        {
            "scope": {"unit": "VND", "scale": 0},
            "data": {
                "contribution_null_reason": None,
                "groups": [
                    {
                        "label": label,
                        "previous": "0",
                        "current": "1",
                        "delta": "1",
                        "net_contribution_pct": "100",
                    }
                    for label in labels
                ],
            },
        }
    )

    assert rendered == labels
    assert list(table["Nhóm"]) == labels
    assert list(chart["Nhóm"]) == labels


def test_power_bi_export_requires_the_matching_validated_artifact():
    report = {
        "status": "COMPLETED",
        "sufficiency_status": "completed",
        "validated_analysis_fingerprint": "abc123",
    }
    assert not _can_export_report(report, None)


def test_missing_or_stale_artifact_never_becomes_authoritative():
    report = {
        "status": "COMPLETED",
        "sufficiency_status": "completed",
        "validated_analysis_fingerprint": "expected",
    }

    assert _validated_artifact(report, None) is None
    assert _validated_artifact(report, {"content_fingerprint": "stale"}) is None
    assert _downloadable_artifact(report, None) is None
    assert not _can_export_report(report, {"content_fingerprint": "stale"})


@pytest.mark.parametrize(
    ("issue", "expected_text", "expected_action", "expected_severity"),
    [
        (
            {"code": "DATE_PARSE_ERROR", "severity": "error", "count": 3},
            "không khớp định dạng",
            "không tự đổi ngày mơ hồ",
            "error",
        ),
        (
            {"code": "COVERAGE_UNKNOWN", "severity": "warning", "count": 1},
            "Chưa xác nhận",
            "không coi khoảng trống là zero",
            "warning",
        ),
        (
            {"code": "NEW_VALIDATOR_CODE", "severity": "error", "count": "bad"},
            "chưa có hướng dẫn chuyên biệt",
            "Không tự sửa dữ liệu",
            "error",
        ),
    ],
)
def test_validation_issue_codes_have_actionable_safe_copy(
    issue, expected_text, expected_action, expected_severity
):
    code, problem, action, count, severity = _validation_issue_presentation(issue)

    assert code == issue["code"]
    assert expected_text in problem
    assert expected_action in action
    assert severity == expected_severity
    assert count == (issue["count"] if isinstance(issue["count"], int) else 1)


def test_null_metric_copy_matches_reject_and_exclude_policies():
    issue = {"code": "NULL_METRIC", "severity": "error", "count": 2}

    rejected = _validation_issue_presentation(issue, metric_null_policy="reject")
    excluded = _validation_issue_presentation(issue, metric_null_policy="exclude")

    assert "chặn phân tích" in rejected[2]
    assert "thay null bằng zero" in rejected[2]
    assert "bỏ các amount thiếu" in excluded[2]
    assert "không diễn giải chúng thành zero" in excluded[2]


def test_partial_needs_input_and_execution_failure_are_distinct():
    partial = _analysis_status_presentation("PARTIAL")
    needs_input = _analysis_status_presentation("NEEDS_INPUT")
    failed = _analysis_status_presentation("FAILED")

    assert partial and partial[0] == "warning" and "JSON vẫn xem/tải được" in partial[1]
    assert needs_input and needs_input[0] == "info" and "không phải lỗi thực thi" in needs_input[1]
    assert failed and failed[0] == "error" and "lỗi vận hành" in failed[1]


def test_partial_artifact_remains_downloadable_but_explains_export_gate(monkeypatch):
    partial_artifact = SimpleNamespace(
        execution_status="succeeded",
        sufficiency_status="partial",
        model_dump=lambda mode: {"sufficiency_status": "partial"},
    )
    monkeypatch.setattr(ui_module, "_validated_artifact", lambda report, payload: partial_artifact)

    assert _downloadable_artifact({}, {}) == {"sufficiency_status": "partial"}
    assert "vẫn có thể tải JSON" in _export_unavailable_message(partial_artifact)


def test_local_ui_full_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("BI_ANALYST_RUNTIME", str(tmp_path / "runtime"))
    monkeypatch.delenv("BI_ANALYST_POLICY", raising=False)
    app = AppTest.from_file(APP, default_timeout=30).run()
    assert not app.exception
    _checkbox(app, "Tôi xác nhận grain, cách tính doanh thu và mappings ở trên").check()
    app.text_input[0].set_value("One sales line; Revenue belongs to that line")
    _button(app, "Kiểm tra dữ liệu và tạo phiên").click().run()
    assert not app.exception
    _button(app, "Chạy phân tích").click().run()
    assert not app.exception
    assert {m.label: m.value for m in app.metric} == {
        "Kỳ trước": "1.000 VND",
        "Kỳ hiện tại": "600 VND",
        "Chênh lệch": "−400 VND",
        "Tăng trưởng": "−40,00%",
    }
    artifacts = list((tmp_path / "runtime").rglob("validated_analysis.json"))
    assert len(artifacts) == 1
    artifact_payload = json.loads(artifacts[0].read_text(encoding="utf-8"))
    current_report = app.session_state["report"]
    assert _downloadable_artifact(current_report, artifact_payload) == artifact_payload
    assert _validated_artifact(current_report, artifact_payload) is not None
    assert _can_export_report(current_report, artifact_payload)
    partial_report = {**current_report, "status": "PARTIAL", "sufficiency_status": "partial"}
    assert _can_export_report(partial_report, artifact_payload)
    mismatched_report = {
        **current_report,
        "validated_analysis_fingerprint": "different-artifact",
    }
    assert _validated_artifact(mismatched_report, artifact_payload) is None
    _button(app, "Tạo Power BI project").click().run()
    assert not app.exception
    assert any("Đã tạo project" in item.value for item in app.success)
    manifests = list((tmp_path / "runtime").rglob("export_manifest.json"))
    assert len(manifests) == 1
    assert json.loads(manifests[0].read_text())["status"] == "generated_not_executed"


def test_missing_validated_artifact_hides_claims_and_blocks_power_bi(tmp_path, monkeypatch):
    monkeypatch.setenv("BI_ANALYST_RUNTIME", str(tmp_path / "runtime"))
    monkeypatch.delenv("BI_ANALYST_POLICY", raising=False)
    original_read = RunStore.read

    def read_without_analysis_artifact(self, run_id, name):
        if name == "validated_analysis.json":
            raise BIError("ARTIFACT_MISSING", "Validated artifact is missing.")
        return original_read(self, run_id, name)

    monkeypatch.setattr(RunStore, "read", read_without_analysis_artifact)
    app = AppTest.from_file(APP, default_timeout=30).run()
    assert not app.exception
    _checkbox(app, "Tôi xác nhận grain, cách tính doanh thu và mappings ở trên").check()
    app.text_input[0].set_value("One sales line; Revenue belongs to that line")
    _button(app, "Kiểm tra dữ liệu và tạo phiên").click().run()
    assert not app.exception
    _button(app, "Chạy phân tích").click().run()
    assert not app.exception
    assert len(app.metric) == 0
    export_button = next(x for x in app.button if x.label == "Tạo Power BI project")
    assert export_button.disabled
    assert any("thiếu validated analysis artifact" in item.value for item in app.warning)


def test_artifact_status_and_limitations_override_mutated_report_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("BI_ANALYST_RUNTIME", str(tmp_path / "runtime"))
    monkeypatch.delenv("BI_ANALYST_POLICY", raising=False)
    original_analyze = ui_module.analyze_deterministic

    def mutate_compatibility_metadata(run_id, store, request):
        report = original_analyze(run_id, store, request)
        report["status"] = "COMPLETED"
        report["sufficiency_status"] = "completed"
        report["limitations"] = []
        report["error"] = None
        report["next_question"] = None
        return report

    monkeypatch.setattr(ui_module, "analyze_deterministic", mutate_compatibility_metadata)
    app = AppTest.from_file(APP, default_timeout=30).run()
    assert not app.exception
    _checkbox(app, "Tôi xác nhận grain, cách tính doanh thu và mappings ở trên").check()
    app.text_input[0].set_value("One sales line; Revenue belongs to that line")
    _button(app, "Kiểm tra dữ liệu và tạo phiên").click().run()
    assert not app.exception
    app.text_area[0].set_value("Why did revenue change?")
    _button(app, "Chạy phân tích").click().run()
    assert not app.exception

    artifacts = list((tmp_path / "runtime").rglob("validated_analysis.json"))
    assert len(artifacts) == 1
    artifact = json.loads(artifacts[0].read_text(encoding="utf-8"))
    assert artifact["sufficiency_status"] == "abstained"
    assert artifact["limitations"]
    assert app.session_state["report"]["status"] == "COMPLETED"
    assert any("chưa đủ" in item.value for item in app.warning)
    assert any("causal inference" in item.value.lower() for item in app.warning)
    export_button = next(x for x in app.button if x.label == "Tạo Power BI project")
    assert export_button.disabled


def test_semantic_confirmation_never_enables_cloud(tmp_path, monkeypatch):
    monkeypatch.setenv("BI_ANALYST_RUNTIME", str(tmp_path / "runtime"))
    monkeypatch.delenv("BI_ANALYST_POLICY", raising=False)
    app = AppTest.from_file(APP, default_timeout=30).run()
    _checkbox(app, "Tôi xác nhận grain, cách tính doanh thu và mappings ở trên").check()
    app.text_input[0].set_value("One sales line; Revenue belongs to that line")
    _button(app, "Kiểm tra dữ liệu và tạo phiên").click().run()
    policies = list((tmp_path / "runtime").rglob("data_policy.json"))
    assert len(policies) == 1
    assert json.loads(policies[0].read_text())["external_llm_enabled"] is False


def test_llm_controls_stay_unavailable_with_dummy_key_and_semantic_stage(
    tmp_path, monkeypatch
):
    runtime = tmp_path / "runtime"
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        DataPolicy(
            dataset_class="synthetic",
            approved_stages=["analysis", "semantic_review"],
        ).model_dump_json(),
        encoding="utf-8",
    )
    monkeypatch.setenv("BI_ANALYST_RUNTIME", str(runtime))
    monkeypatch.setenv("BI_ANALYST_POLICY", str(policy_path))
    monkeypatch.setenv("BI_ANALYST_MODEL", "dummy-model-must-not-be-used")

    def fail_if_adapter_is_created(*args, **kwargs):
        pytest.fail("Unavailable LLM controls must not create an adapter")

    monkeypatch.setattr(provider_module, "OpenAIAdapter", fail_if_adapter_is_created)

    app = AppTest.from_file(APP, default_timeout=30).run()
    assert not app.exception
    mapping_button = _button(app, "LLM đề xuất mappings — chưa bật")
    assert mapping_button.disabled

    _checkbox(app, "Tôi xác nhận grain, cách tính doanh thu và mappings ở trên").check()
    app.text_input[0].set_value("One sales line; Revenue belongs to that line")
    _button(app, "Kiểm tra dữ liệu và tạo phiên").click().run()

    assert not app.exception
    analysis_mode = next(item for item in app.radio if item.label == "Cách phân tích")
    assert analysis_mode.options == [
        "Phân tích cục bộ bằng Python",
        "LLM agent — chưa bật trong ứng dụng",
    ]
    assert analysis_mode.form_id == ""
    assert analysis_mode.value == "Phân tích cục bộ bằng Python"
    assert sum("Đã đánh giá riêng; chưa bật trong ứng dụng" in item.value for item in app.caption) >= 2

    analysis_mode.set_value("LLM agent — chưa bật trong ứng dụng").run()
    assert _button(app, "Chạy phân tích").disabled
    assert "report" not in app.session_state

    analysis_mode = next(item for item in app.radio if item.label == "Cách phân tích")
    analysis_mode.set_value("Phân tích cục bộ bằng Python").run()
    assert not _button(app, "Chạy phân tích").disabled
    assert "report" not in app.session_state
