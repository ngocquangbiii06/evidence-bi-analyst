"""Single-user local experience with session-scoped storage and explicit semantics."""

from __future__ import annotations

import io
import json
import os
import uuid
import zipfile
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from .bi import export_powerbi
from .contracts import (
    AnalysisRequest,
    BusinessContract,
    DataPolicy,
    Metric,
    Period,
    ValidatedAnalysisArtifact,
)
from .data import duplicate_counts, load_csv_bytes
from .errors import BIError
from .semantics import propose_semantics
from .store import RunStore, cleanup_expired_sessions
from .workflow import analyze_deterministic, ingest_run

ROOT = Path(__file__).resolve().parents[2]

UNAVAILABLE = "Chưa đủ dữ liệu"


_VALIDATION_ISSUE_COPY = {
    "NO_DATA": (
        "CSV không có dòng dữ liệu.",
        "Bổ sung ít nhất một dòng dữ liệu rồi tạo phiên mới.",
    ),
    "SEMANTICS_UNCONFIRMED": (
        "Ý nghĩa nghiệp vụ chưa được xác nhận.",
        "Kiểm tra grain, Revenue, ngày và dimensions rồi xác nhận lại.",
    ),
    "SEMANTICS_INCOMPLETE": (
        "Mapping nghiệp vụ còn thiếu.",
        "Khai báo grain line-item, cột ngày và cột Revenue cộng được trước khi tiếp tục.",
    ),
    "MISSING_COLUMNS": (
        "Một hoặc nhiều cột đã mapping không có trong CSV.",
        "Chọn lại mapping theo header hiện có hoặc tải đúng CSV; ứng dụng không tự đoán cột thay thế.",
    ),
    "NULL_KEY": (
        "Khóa dòng hàng có giá trị thiếu.",
        "Bổ sung khóa cho các dòng bị thiếu hoặc chọn khóa dòng hàng đúng; không có row ID chi tiết để tự sửa.",
    ),
    "DUPLICATE_KEY": (
        "Khóa dòng hàng không duy nhất.",
        "Kiểm tra lại grain và các cột khóa. Policy hiện tại không tự gộp hoặc xóa dòng trùng.",
    ),
    "NO_ROW_KEY": (
        "Chưa khai báo khóa dòng hàng nên chưa chứng minh được tính duy nhất.",
        "Chọn các cột tạo thành khóa line-item nếu dataset có khóa đáng tin cậy.",
    ),
    "DUPLICATE_ROWS": (
        "Có các dòng nguồn giống hệt nhau.",
        "Đối chiếu nguồn và grain. Ứng dụng không tự xóa dòng trùng.",
    ),
    "DATE_PARSE_ERROR": (
        "Có giá trị ngày không khớp định dạng đã chọn.",
        "Chọn đúng định dạng ngày hoặc sửa giá trị trong CSV; ứng dụng không tự đổi ngày mơ hồ.",
    ),
    "NULL_DATE": (
        "Cột ngày phân tích có giá trị thiếu.",
        "Bổ sung ngày hợp lệ cho các dòng này trước khi phân tích hai kỳ.",
    ),
    "UNSUPPORTED_METRIC_TYPE": (
        "Metric không phải Revenue cộng được.",
        "Dùng mapping Revenue additive theo hợp đồng flagship.",
    ),
    "MONEY_PARSE_ERROR": (
        "Có giá trị Revenue sai định dạng, precision hoặc phạm vi.",
        "Sửa giá trị nguồn theo currency/scale đã xác nhận; ứng dụng không tự làm tròn hoặc ép kiểu.",
    ),
    "NEGATIVE_VALUES": (
        "Revenue có giá trị âm.",
        "Giữ nguyên nếu đây là returns theo policy hiện tại; không tự xóa giá trị âm.",
    ),
    "MONEY_OVERFLOW": (
        "Tổng Revenue vượt phạm vi số cố định được hỗ trợ.",
        "Kiểm tra unit/scale và dữ liệu nguồn trước khi tạo phiên mới.",
    ),
    "CURRENCY_MISMATCH": (
        "Giá trị currency không khớp đơn vị Revenue đã xác nhận.",
        "Chọn đúng currency hoặc sửa dữ liệu nguồn; một dataset chỉ dùng một currency.",
    ),
    "COVERAGE_UNKNOWN": (
        "Chưa xác nhận dữ liệu bao phủ đầy đủ khoảng khai báo.",
        "Chỉ chọn xác nhận coverage khi biết chắc dữ liệu đầy đủ; nếu chưa biết, giữ cảnh báo và không coi khoảng trống là zero.",
    ),
    "OUTSIDE_COVERAGE": (
        "Có bản ghi nằm ngoài khoảng coverage đã xác nhận.",
        "Đối chiếu khoảng coverage với nguồn rồi tạo phiên mới; không tự loại bản ghi.",
    ),
}


def _validation_issue_presentation(
    issue: dict, *, metric_null_policy: str = "reject"
) -> tuple[str, str, str, int, str]:
    """Return safe, actionable copy without inventing row-level diagnostics."""
    code = str(issue.get("code") or "UNKNOWN_ISSUE")
    severity = "warning" if issue.get("severity") == "warning" else "error"
    try:
        count = max(0, int(issue.get("count", 1)))
    except (TypeError, ValueError):
        count = 1
    if code == "NULL_METRIC":
        problem = "Revenue có giá trị thiếu."
        if metric_null_policy == "exclude":
            action = (
                "Policy exclude sẽ bỏ các amount thiếu khỏi phép cộng nhưng vẫn giữ limitation; "
                "không diễn giải chúng thành zero."
            )
        else:
            action = (
                "Policy reject hiện tại chặn phân tích. Bổ sung Revenue hợp lệ trong CSV; "
                "ứng dụng không tự thay null bằng zero."
            )
    else:
        problem, action = _VALIDATION_ISSUE_COPY.get(
            code,
            (
                "Hệ thống phát hiện một vấn đề chưa có hướng dẫn chuyên biệt.",
                "Không tự sửa dữ liệu. Xem mã và chi tiết kỹ thuật, rồi kiểm tra lại CSV và mappings.",
            ),
        )
    return code, problem, action, count, severity


def _analysis_status_presentation(status: str | None) -> tuple[str, str] | None:
    """Keep analytical sufficiency distinct from operational execution failures."""
    if status == "PARTIAL":
        return (
            "warning",
            "Phân tích hoàn thành một phần: các quan sát được chấp nhận và file JSON vẫn xem/tải được, nhưng còn thiếu nghĩa vụ nên chưa thể xuất Power BI đầy đủ.",
        )
    if status == "ABSTAINED":
        return (
            "warning",
            "Phân tích đã chạy nhưng bằng chứng hiện có chưa đủ để đưa ra kết luận được hỗ trợ.",
        )
    if status == "NEEDS_INPUT":
        return (
            "info",
            "Phân tích đang chờ một xác nhận về semantics hoặc phạm vi; đây không phải lỗi thực thi.",
        )
    if status in {"FAILED", "CANCELLED", "EXPIRED"}:
        return (
            "error",
            "Lượt chạy gặp lỗi vận hành, bị hủy hoặc hết hạn; không có kết luận được xác nhận.",
        )
    return None


def _export_unavailable_message(artifact: ValidatedAnalysisArtifact | None) -> str:
    if artifact is None:
        return "Chưa có analysis artifact hợp lệ khớp với lượt đang hiển thị nên không thể xuất Power BI."
    if artifact.execution_status != "succeeded":
        return "Lượt chạy chưa hoàn tất thành công nên không thể xuất Power BI."
    return {
        "partial": "Kết quả còn thiếu nghĩa vụ bắt buộc; vẫn có thể tải JSON, nhưng chưa thể xuất Power BI đầy đủ.",
        "abstained": "Bằng chứng chưa đủ cho kết luận; vẫn có thể tải JSON, nhưng không tạo dashboard có vẻ đã hoàn tất.",
        "needs_input": "Cần xác nhận thêm semantics hoặc phạm vi trước khi xuất Power BI đầy đủ.",
    }.get(
        artifact.sufficiency_status,
        "Chỉ analysis artifact completed mới đủ điều kiện xuất Power BI.",
    )


def _render_validation_report(validation: dict, contract: BusinessContract) -> None:
    readiness = validation.get("analysis_readiness")
    if readiness == "ready":
        st.success("Dữ liệu đã qua kiểm tra và sẵn sàng cho phân tích cục bộ.")
    else:
        st.error("Dữ liệu chưa sẵn sàng. Giữ nguyên các lỗi chặn và xử lý từng mục bên dưới.")
    null_policy = contract.metric("Revenue").null_policy
    for issue in validation.get("issues", []):
        code, problem, action, count, severity = _validation_issue_presentation(
            issue, metric_null_policy=null_policy
        )
        getattr(st, severity)(f"{code} · {problem} Số lượng: {count}.")
        st.caption("Cách xử lý: " + action)
    with st.expander("Mã và dữ liệu kiểm tra kỹ thuật", expanded=False):
        st.json(validation)


def _suggested_column_index(columns: list[str], suggestion: str | None) -> int | None:
    """Do not silently replace an unresolved semantic suggestion with the first column."""
    return columns.index(suggestion) if suggestion in columns else None


def _validated_artifact(report: dict, artifact_payload: object) -> ValidatedAnalysisArtifact | None:
    """Load the artifact only when it matches the analysis currently shown in the UI."""
    expected_fingerprint = report.get("validated_analysis_fingerprint")
    if not isinstance(expected_fingerprint, str) or not expected_fingerprint:
        return None
    if not isinstance(artifact_payload, dict):
        return None
    try:
        artifact = ValidatedAnalysisArtifact.model_validate(artifact_payload)
    except (TypeError, ValueError):
        return None
    return artifact if artifact.content_fingerprint == expected_fingerprint else None


def _root_comparison_result(artifact: ValidatedAnalysisArtifact | None) -> dict | None:
    """Select KPI evidence only by the validated artifact's explicit root IDs."""
    if artifact is None:
        return None
    for evidence_id in artifact.root_evidence_ids:
        result = artifact.evidence_registry.get(evidence_id)
        if result is None:
            result = next(
                (
                    item
                    for item in artifact.evidence_registry.values()
                    if isinstance(item, dict) and item.get("evidence_id") == evidence_id
                ),
                None,
            )
        if (
            isinstance(result, dict)
            and result.get("evidence_id") == evidence_id
            and result.get("tool") == "compare_periods"
            and isinstance(result.get("scope"), dict)
            and result["scope"].get("dimension") is None
        ):
            return result
    return None


def _plain_mapping(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return {}


def _plain_label(value: object, *, null_label: str = "(Thiếu giá trị)") -> str:
    """Return visible plain text while keeping null and empty strings distinct."""
    if value is None:
        return null_label
    text = str(value)
    if text == "":
        return "(Chuỗi rỗng)"
    return text


def _render_plain_text(value: object, *, null_label: str = "(Thiếu giá trị)") -> None:
    """Render dynamic labels without allowing Markdown links or emphasis."""
    st.text(_plain_label(value, null_label=null_label))


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def _format_number(value: object, *, scale: int, signed: bool = False) -> str:
    number = _decimal(value)
    if number is None:
        return UNAVAILABLE
    quantum = Decimal(1).scaleb(-scale)
    rounded = number.quantize(quantum, rounding=ROUND_HALF_UP)
    absolute = f"{abs(rounded):,.{scale}f}"
    localized = absolute.replace(",", "_").replace(".", ",").replace("_", ".")
    if rounded < 0:
        return "−" + localized
    if signed and rounded > 0:
        return "+" + localized
    return localized


def _format_money(value: object, *, unit: str, scale: int, signed: bool = False) -> str:
    formatted = _format_number(value, scale=scale, signed=signed)
    return formatted if formatted == UNAVAILABLE else f"{formatted} {_plain_label(unit)}"


def _format_percent(value: object, *, signed: bool = False) -> str:
    formatted = _format_number(value, scale=2, signed=signed)
    return formatted if formatted == UNAVAILABLE else formatted + "%"


def _observed_amount(bucket: object) -> object:
    values = _plain_mapping(bucket)
    if not values:
        return None
    status = values.get("status")
    is_observed = status in {None, "observed"}
    is_confirmed_zero = status == "known_zero" and values.get("coverage_confirmed") is True
    if not (is_observed or is_confirmed_zero):
        return None
    return values.get("amount")


def _observed_group_value(row: dict[str, Any], field: str) -> object:
    status = row.get(f"{field}_status")
    is_observed = status in {None, "observed"}
    is_confirmed_zero = (
        status == "known_zero" and row.get(f"{field}_coverage_confirmed") is True
    )
    if not (is_observed or is_confirmed_zero):
        return None
    return row.get(field)


def _kpi_presentation(result: dict | None) -> list[tuple[str, str]]:
    """Format authoritative comparison fields without deriving missing values."""
    if result is None:
        return []
    scope = _plain_mapping(result.get("scope"))
    data = _plain_mapping(result.get("data"))
    unit = str(scope.get("unit") or "")
    try:
        scale = int(scope.get("scale", 0))
    except (TypeError, ValueError):
        scale = 0
    return [
        (
            "Kỳ trước",
            _format_money(_observed_amount(data.get("previous")), unit=unit, scale=scale),
        ),
        (
            "Kỳ hiện tại",
            _format_money(_observed_amount(data.get("current")), unit=unit, scale=scale),
        ),
        (
            "Chênh lệch",
            _format_money(data.get("delta"), unit=unit, scale=scale, signed=True),
        ),
        ("Tăng trưởng", _format_percent(data.get("growth_pct"), signed=True)),
    ]


def _period_label(period: object) -> str:
    values = _plain_mapping(period)
    start = _plain_label(values.get("start"), null_label=UNAVAILABLE)
    end = _plain_label(values.get("end"), null_label=UNAVAILABLE)
    return f"[{start}, {end})"


def _filter_label(filters: object) -> str:
    values = _plain_mapping(filters)
    if not values:
        return "Tất cả trong phạm vi dữ liệu đã xuất"
    parts = []
    for dimension in sorted(values, key=str):
        raw_items = values[dimension]
        items = raw_items if isinstance(raw_items, list) else [raw_items]
        rendered = ", ".join(_plain_label(item) for item in items)
        parts.append(f"{_plain_label(dimension)} = {rendered}")
    return "; ".join(parts)


def _scope_label(
    scope: object,
    *,
    is_root: bool = False,
    group_label: object = None,
    has_group: bool = False,
) -> str:
    """Produce a complete business label; never shorten filters or merge null with empty."""
    values = _plain_mapping(scope)
    metric = _plain_label(values.get("metric_id"), null_label=UNAVAILABLE)
    unit = _plain_label(values.get("unit"), null_label=UNAVAILABLE)
    scale = _plain_label(values.get("scale"), null_label=UNAVAILABLE)
    parts = [
        f"Chỉ số: {metric} · Đơn vị: {unit} · Scale: {scale}",
        f"Kỳ trước: {_period_label(values.get('previous'))}",
        f"Kỳ hiện tại: {_period_label(values.get('current'))}",
        f"Bộ lọc: {_filter_label(values.get('filters'))}",
    ]
    parts.append("Phạm vi gốc" if is_root else "Phạm vi phân tích")
    dimension = values.get("dimension")
    if dimension is not None and has_group:
        parts.append(f"Nhóm: {_plain_label(dimension)} = {_plain_label(group_label)}")
    elif dimension is not None:
        parts.append(f"Chiều phân tích: {_plain_label(dimension)}")
    return " · ".join(parts)


def _evidence_sections(
    artifact: ValidatedAnalysisArtifact | None,
) -> tuple[list[dict], list[dict]]:
    """Return root breakdowns in request order, then every non-root evidence record."""
    if artifact is None:
        return [], []
    root_ids = set(artifact.root_evidence_ids)
    dimension_order = {
        dimension: index for index, dimension in enumerate(artifact.root_request.dimensions)
    }
    root_breakdowns = [
        artifact.evidence_registry[evidence_id]
        for evidence_id in artifact.root_evidence_ids
        if evidence_id in artifact.evidence_registry
        and artifact.evidence_registry[evidence_id].get("tool") == "breakdown_change"
    ]
    root_breakdowns.sort(
        key=lambda result: (
            dimension_order.get(_plain_mapping(result.get("scope")).get("dimension"), 10_000),
            str(result.get("evidence_id", "")),
        )
    )
    narrowed = [
        result
        for evidence_id, result in artifact.evidence_registry.items()
        if evidence_id not in root_ids and isinstance(result, dict)
    ]
    narrowed.sort(
        key=lambda result: (
            str(_plain_mapping(result.get("scope")).get("dimension") or ""),
            _filter_label(_plain_mapping(result.get("scope")).get("filters")),
            str(result.get("tool", "")),
            str(result.get("evidence_id", "")),
        )
    )
    return root_breakdowns, narrowed


def _breakdown_presentation(result: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    scope = _plain_mapping(result.get("scope"))
    data = _plain_mapping(result.get("data"))
    unit = str(scope.get("unit") or "")
    try:
        scale = int(scope.get("scale", 0))
    except (TypeError, ValueError):
        scale = 0
    rows = []
    chart_rows = []
    contribution_available = data.get("contribution_null_reason") is None
    for raw_row in data.get("groups", []):
        row = _plain_mapping(raw_row)
        label = _plain_label(row.get("label"))
        previous = _observed_group_value(row, "previous")
        current = _observed_group_value(row, "current")
        delta = row.get("delta") if previous is not None and current is not None else None
        contribution = row.get("net_contribution_pct") if contribution_available else None
        rows.append(
            {
                "Nhóm": label,
                "Kỳ trước": _format_money(previous, unit=unit, scale=scale),
                "Kỳ hiện tại": _format_money(current, unit=unit, scale=scale),
                "Chênh lệch": _format_money(delta, unit=unit, scale=scale, signed=True),
                "Đóng góp vào biến động ròng (%)": _format_percent(
                    contribution, signed=True
                ),
            }
        )
        chart_delta = _decimal(delta)
        if chart_delta is not None:
            chart_rows.append({"Nhóm": label, "Chênh lệch": float(chart_delta)})
    columns = [
        "Nhóm",
        "Kỳ trước",
        "Kỳ hiện tại",
        "Chênh lệch",
        "Đóng góp vào biến động ròng (%)",
    ]
    return pd.DataFrame(rows, columns=columns), pd.DataFrame(
        chart_rows, columns=["Nhóm", "Chênh lệch"]
    )


def _accepted_findings(artifact: ValidatedAnalysisArtifact | None) -> list:
    """Return only findings whose verdict is part of the validated artifact."""
    if artifact is None:
        return []
    return [record for record in artifact.findings if record.validation.accepted is True]


def _can_export_report(report: dict, artifact_payload: object) -> bool:
    artifact = _validated_artifact(report, artifact_payload)
    return bool(
        artifact is not None
        and artifact.execution_status == "succeeded"
        and artifact.sufficiency_status == "completed"
    )


def _artifact_status(artifact: ValidatedAnalysisArtifact | None) -> str | None:
    if artifact is None:
        return None
    if artifact.execution_status == "succeeded":
        return {
            "completed": "COMPLETED",
            "partial": "PARTIAL",
            "abstained": "ABSTAINED",
            "needs_input": "NEEDS_INPUT",
        }[artifact.sufficiency_status]
    return {
        "failed": "FAILED",
        "cancelled": "CANCELLED",
        "expired": "EXPIRED",
    }[artifact.execution_status]


def _downloadable_artifact(report: dict, artifact_payload: object) -> dict | None:
    """Bind the downloadable authoritative artifact to the report currently on screen."""
    artifact = _validated_artifact(report, artifact_payload)
    if artifact is None:
        return None
    return artifact.model_dump(mode="json")


def show_report(report, artifact_payload: object = None):
    artifact = _validated_artifact(report, artifact_payload)
    overall = _root_comparison_result(artifact)
    status = _artifact_status(artifact)
    validated_artifact_present = artifact is not None
    if not validated_artifact_present:
        st.warning(
            "Báo cáo cũ hoặc thiếu validated analysis artifact. Chạy lại để chỉ hiển thị kết quả đã xác nhận."
        )
        st.info("Không hiển thị KPI, biểu đồ hoặc kết luận từ nguồn không còn khớp.")
        return

    st.subheader("Kết quả phân tích doanh thu")
    st.caption("Câu hỏi nghiệp vụ")
    _render_plain_text(artifact.root_request.question, null_label=UNAVAILABLE)
    summary_columns = st.columns(4)
    summary_columns[0].caption("Hai kỳ")
    summary_columns[0].text(
        f"{_period_label(artifact.root_request.previous)} → "
        f"{_period_label(artifact.root_request.current)}"
    )
    summary_columns[1].caption("Phạm vi gốc")
    summary_columns[1].text(_filter_label(artifact.root_scope.filters))
    summary_columns[2].caption("Chế độ")
    summary_columns[2].text(
        {
            "deterministic": "Python cục bộ (deterministic)",
            "test_adapter": "Adapter kiểm thử",
            "live_agent": "LLM agent đã ghi nhận",
        }[artifact.mode]
    )
    summary_columns[3].caption("Trạng thái")
    summary_columns[3].text(
        {
            "COMPLETED": "Hoàn tất",
            "PARTIAL": "Hoàn thành một phần",
            "ABSTAINED": "Chưa đủ bằng chứng",
            "NEEDS_INPUT": "Cần thêm xác nhận",
            "FAILED": "Lỗi vận hành",
            "CANCELLED": "Đã hủy",
            "EXPIRED": "Đã hết hạn",
        }.get(status, UNAVAILABLE)
    )
    _render_plain_text(_scope_label(artifact.root_scope, is_root=True))
    contract = artifact.confirmed_contract_snapshot
    if contract.coverage_confirmed and contract.coverage is not None:
        _render_plain_text(
            "Coverage do người cung cấp xác nhận: "
            + _period_label(contract.coverage)
            + ". Đây là xác nhận đầu vào, không phải kiểm chứng độc lập về độ đầy đủ."
        )
    else:
        st.warning(
            "Coverage chưa được người cung cấp xác nhận; khoảng trống không được diễn giải thành zero."
        )

    status_presentation = _analysis_status_presentation(status)
    if status_presentation:
        level, message = status_presentation
        getattr(st, level)(message)

    st.subheader("Tổng quan doanh thu")
    if overall:
        cols = st.columns(4)
        for column, (title, value) in zip(cols, _kpi_presentation(overall)):
            column.metric(title, value)
        for warning in overall.get("warnings", []):
            st.warning(
                {
                    "COVERAGE_UNKNOWN": "Chưa xác nhận dữ liệu đầy đủ cho hai kỳ.",
                    "PERIOD_LENGTHS_DIFFER": "Hai kỳ có số ngày khác nhau; đang so sánh tổng, chưa chuẩn hóa theo ngày.",
                }.get(warning, warning)
            )
    else:
        st.info("Không có bằng chứng so sánh kỳ ở phạm vi gốc; KPI không được suy ra.")

    root_breakdowns, narrowed_evidence = _evidence_sections(artifact)
    if root_breakdowns:
        st.subheader("Đóng góp theo phạm vi gốc")
        st.caption(
            "Mỗi dimension là một lát cắt độc lập của cùng biến động ròng; không cộng các bảng với nhau."
        )
        for result in root_breakdowns:
            scope = _plain_mapping(result.get("scope"))
            dimension = _plain_label(scope.get("dimension"), null_label=UNAVAILABLE)
            st.markdown("#### Đóng góp theo")
            _render_plain_text(dimension)
            _render_plain_text(_scope_label(scope, is_root=True))
            display, chart = _breakdown_presentation(result)
            st.dataframe(display, hide_index=True, width="stretch")
            if not chart.empty:
                st.bar_chart(chart, x="Nhóm", y="Chênh lệch", color="#0D9488")
            else:
                st.info("Không có chênh lệch quan sát để vẽ biểu đồ cho phạm vi này.")
            st.caption(
                "Đóng góp = 100 × chênh lệch nhóm / chênh lệch ròng; tỷ lệ có thể lớn hơn "
                "100%, âm, hoặc Chưa đủ dữ liệu khi mẫu số bằng 0. Đây không phải thị phần."
            )

    findings = _accepted_findings(artifact)
    st.subheader("Kết luận đã được chấp nhận")
    if not findings:
        st.info("Artifact không có kết luận nào đã vượt qua toàn bộ kiểm tra.")
    for finding in findings:
        candidate = finding.candidate
        claim_label = "Quan sát" if candidate.claim_type == "observation" else "Đóng góp"
        st.markdown(f"**{candidate.finding_id} · {claim_label}**")
        _render_plain_text(candidate.text, null_label=UNAVAILABLE)
        _render_plain_text(
            _scope_label(
                candidate.scope,
                is_root=candidate.evidence_id in set(artifact.root_evidence_ids),
                group_label=candidate.label,
                has_group=candidate.group_index is not None,
            )
        )

    if narrowed_evidence:
        st.subheader("Bằng chứng ở phạm vi thu hẹp")
        st.info(
            "Các số dưới đây thuộc phạm vi riêng đã ghi trong artifact; không thay thế KPI của phạm vi gốc."
        )
        for result in narrowed_evidence:
            scope = _plain_mapping(result.get("scope"))
            if result.get("tool") == "breakdown_change":
                st.markdown("#### Phân rã theo")
                _render_plain_text(scope.get("dimension"))
            else:
                st.markdown("#### So sánh hai kỳ")
            _render_plain_text(_scope_label(scope))
            if result.get("tool") == "breakdown_change":
                display, chart = _breakdown_presentation(result)
                st.dataframe(display, hide_index=True, width="stretch")
                if not chart.empty:
                    st.bar_chart(chart, x="Nhóm", y="Chênh lệch", color="#0D9488")
            elif result.get("tool") == "compare_periods":
                comparison = dict(_kpi_presentation(result))
                st.dataframe(
                    pd.DataFrame([comparison]), hide_index=True, width="stretch"
                )

    st.subheader("Giới hạn và phần còn thiếu")
    for limitation in artifact.limitations:
        st.warning(_plain_label(limitation))
    if artifact.obligations.missing:
        st.info(
            "Các nghĩa vụ chưa đủ bằng chứng: "
            + ", ".join(_plain_label(item) for item in artifact.obligations.missing)
        )
    for error in artifact.errors:
        st.error(_plain_label(error.message))
    if artifact.clarification_request:
        st.info(_plain_label(artifact.clarification_request))
    if not artifact.limitations and not artifact.obligations.missing and not artifact.errors:
        st.caption("Artifact không ghi nhận giới hạn bổ sung.")

    with st.expander("Bằng chứng kỹ thuật và file nguồn", expanded=False):
        st.caption(
            "Phần này giữ mã, validation, trace và usage để đối chiếu; nội dung không thay đổi kết luận ở trên."
        )
        for finding in findings:
            candidate = finding.candidate
            st.json(
                {
                    "finding_id": candidate.finding_id,
                    "evidence_id": candidate.evidence_id,
                    "scope": candidate.scope.model_dump(mode="json"),
                    "field_refs": candidate.field_refs,
                    "validation": finding.validation.model_dump(mode="json"),
                },
                expanded=False,
            )
        st.json(
            {
                "content_fingerprint": artifact.content_fingerprint,
                "dataset_hash": artifact.dataset_hash,
                "contract_fingerprint": artifact.contract_fingerprint,
                "root_evidence_ids": artifact.root_evidence_ids,
                "evidence_registry": artifact.evidence_registry,
                "investigation_trace": [
                    item.model_dump(mode="json") for item in artifact.investigation_trace
                ],
                "usage": artifact.usage.model_dump(mode="json"),
            },
            expanded=False,
        )
        downloadable_artifact = _downloadable_artifact(report, artifact_payload)
        st.download_button(
            "Tải validated analysis JSON",
            json.dumps(downloadable_artifact, ensure_ascii=False, indent=2),
            "validated_analysis.json",
            "application/json",
        )


def main():
    st.set_page_config(page_title="Evidence BI Analyst", page_icon="📊", layout="wide")
    st.title("Evidence BI Analyst")
    st.caption("Phân tích có bằng chứng · Xác nhận định nghĩa dữ liệu · Xuất Power BI")
    if "owner" not in st.session_state:
        st.session_state.owner = uuid.uuid4().hex
    store = RunStore(owner=st.session_state.owner)
    cleanup_expired_sessions(store.root)
    st.sidebar.header("Môi trường")
    st.sidebar.success("Ứng dụng local · 127.0.0.1")
    running = "job" in st.session_state and not st.session_state.job.done()
    st.sidebar.caption(
        "Dữ liệu doanh nghiệp thật mặc định không được gửi cloud. File export có thể chứa dữ liệu của phiên."
    )
    source = st.sidebar.radio("Nguồn dữ liệu", ["Dữ liệu sales giả lập", "Upload CSV"])
    uploaded = None
    if source == "Upload CSV":
        uploaded = st.file_uploader("CSV UTF-8, tối đa 50 MiB", type=["csv"])
        if uploaded is None:
            st.info("Chọn CSV để bắt đầu. Chưa có dữ liệu nào được gửi tới LLM.")
            return
    raw = (ROOT / "examples/sales.csv").read_bytes() if uploaded is None else uploaded.getvalue()
    policy = DataPolicy(dataset_class="synthetic" if uploaded is None else "unknown")
    configured_policy = os.getenv("BI_ANALYST_POLICY")
    if configured_policy:
        try:
            with Path(configured_policy).open("rb") as config_stream:
                config_bytes = config_stream.read(65_537)
            if len(config_bytes) > 65_536:
                raise ValueError("Policy too large")
            policy = DataPolicy.model_validate_json(config_bytes)
        except (OSError, ValueError):
            st.error("Policy backend chưa hợp lệ hoặc không đọc được.")
            return
    try:
        dataset = load_csv_bytes(raw, policy)
    except BIError as error:
        st.error(error.code + ": " + error.message)
        return
    columns = list(dataset.frame.columns)
    if not len(dataset.frame):
        st.error("CSV chỉ có header, chưa có dữ liệu để phân tích.")
        return
    st.subheader("1 · Xác nhận ý nghĩa dữ liệu")
    if st.session_state.get("proposal_hash") != dataset.sha256:
        st.session_state.semantic_proposal = propose_semantics(dataset)
        st.session_state.proposal_hash = dataset.sha256
    proposal = st.session_state.semantic_proposal
    suggested = proposal["mappings"]
    st.caption(
        f"{len(dataset.frame):,} dòng · {len(columns)} cột. Gợi ý local dựa trên tên cột và profile; cần bạn xác nhận."
    )
    with st.expander("Bằng chứng cho đề xuất và những điều chưa biết"):
        st.json(proposal)
    st.button("LLM đề xuất mappings — chưa bật", disabled=True)
    st.caption("Đã đánh giá riêng; chưa bật trong ứng dụng. Mapping hiện tại chỉ dùng gợi ý local.")

    with st.form("semantics"):
        left, right = st.columns(2)
        with left:
            date_column = st.selectbox(
                "Cột ngày phân tích",
                columns,
                index=_suggested_column_index(columns, suggested["date_column"]),
                placeholder="Chọn cột ngày",
            )
            date_formats = ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"]
            date_format = st.selectbox(
                "Định dạng ngày",
                date_formats,
                index=_suggested_column_index(date_formats, suggested["date_format"]),
                placeholder="Chọn định dạng ngày",
                help="Ví dụ: 2026-09-25 dùng %Y-%m-%d; 25/09/2026 dùng %d/%m/%Y. Ứng dụng không tự đoán ngày mơ hồ.",
            )
            key_columns = st.multiselect(
                "Khóa dòng hàng", columns, default=suggested["row_key_columns"]
            )
            grain = st.text_input(
                "Một dòng đại diện cho gì?",
                value="",
                placeholder="Ví dụ: một line-item của đơn hàng; Revenue thuộc line-item đó",
                help="Mô tả đơn vị nghiệp vụ của đúng một dòng để kiểm tra khóa và dòng trùng.",
            )
        with right:
            revenue_column = st.selectbox(
                "Cột doanh thu đã tính",
                columns,
                index=_suggested_column_index(columns, suggested["metric_column"]),
                placeholder="Chọn cột Revenue đã tính",
            )
            currency = st.selectbox(
                "Đồng tiền",
                ["VND", "USD", "EUR"],
                help="Chọn đơn vị của toàn bộ cột Revenue. Flagship không quy đổi nhiều currency.",
            )
            scale = st.number_input(
                "Số chữ số thập phân được phép",
                min_value=0,
                max_value=4,
                value=0 if currency == "VND" else 2,
            )
            grouping = st.multiselect(
                "Phân tích theo nhóm",
                columns,
                default=suggested["dimension_columns"],
            )
        coverage = st.checkbox(
            "Tôi xác nhận dữ liệu đầy đủ trong khoảng khai báo",
            value=uploaded is None,
            help="Chỉ xác nhận khi nguồn có đủ mọi dòng trong [ngày đầu, ngày kết thúc). Min/max ngày không tự chứng minh coverage.",
        )
        c1, c2 = st.columns(2)
        coverage_start = c1.date_input("Ngày đầu dữ liệu đầy đủ", value=date(2026, 1, 1))
        coverage_end = c2.date_input(
            "Ngày kết thúc (không bao gồm ngày này)", value=date(2026, 3, 1)
        )
        confirmed = st.checkbox("Tôi xác nhận grain, cách tính doanh thu và mappings ở trên")
        submitted = st.form_submit_button(
            "Kiểm tra dữ liệu và tạo phiên", type="primary", disabled=running
        )
    if key_columns:
        stats = duplicate_counts(
            list(dataset.frame[key_columns].itertuples(index=False, name=None))
        )
        st.caption(
            f"Khóa đề xuất: {stats['duplicated_groups']} nhóm trùng; {stats['involved_rows']} dòng thuộc nhóm trùng; {stats['excess_rows']} dòng dư."
        )
    if submitted:
        if not confirmed:
            st.warning("Cần xác nhận ý nghĩa dữ liệu trước khi phân tích.")
        elif (
            not grain.strip()
            or date_column is None
            or date_format is None
            or revenue_column is None
            or not grouping
        ):
            st.warning(
                "Chọn rõ cột ngày, định dạng ngày, Revenue, ít nhất một chiều phân tích và grain trước khi xác nhận."
            )
        else:
            try:
                dimensions = {
                    column
                    if column.isascii() and column.isidentifier()
                    else f"Group{i + 1}": column
                    for i, column in enumerate(grouping)
                }
                contract = BusinessContract(
                    confirmed=True,
                    grain_description=grain,
                    row_key_columns=key_columns,
                    date_column=date_column,
                    date_format=date_format,
                    metrics=[
                        Metric(id="Revenue", column=revenue_column, unit=currency, scale=scale)
                    ],
                    dimensions=dimensions,
                    coverage=Period(start=coverage_start, end=coverage_end) if coverage else None,
                    coverage_confirmed=coverage,
                )
                # A separately prepared operator policy is required for cloud. Semantic confirmation never enables it.
                run_id = ingest_run(
                    raw,
                    contract,
                    policy,
                    store,
                    policy_path=Path(configured_policy) if configured_policy else None,
                )
                store.write(run_id, "semantic_proposal.json", proposal)
                st.session_state.run_id = run_id
                st.session_state.contract = contract.model_dump(mode="json")
                st.session_state.source_hash = dataset.sha256
                st.session_state.pop("report", None)
                st.session_state.pop("export_zip", None)
                st.session_state.pop("bi_plan", None)
            except (BIError, ValidationError, OSError):
                st.error(
                    "Cấu hình dữ liệu hoặc policy chưa hợp lệ. Kiểm tra các trường và quyền đọc cấu hình."
                )
    if "run_id" not in st.session_state:
        return
    if dataset.sha256 != st.session_state.get("source_hash"):
        st.warning("Nguồn CSV đã thay đổi. Tạo phiên mới trước khi phân tích tiếp.")
        return
    run_id = st.session_state.run_id
    try:
        manifest = store.manifest(run_id)
    except BIError as error:
        for state_key in ["run_id", "report", "request", "export_zip", "bi_plan"]:
            st.session_state.pop(state_key, None)
        st.warning(error.message + " Tạo phiên mới để tiếp tục.")
        return
    st.sidebar.caption(
        "Phiên được giữ đến khi xóa."
        if manifest["saved"]
        else "Phiên tạm · hết hạn " + manifest["expires_at"]
    )
    if st.sidebar.button("Giữ phiên đến khi tự xóa", disabled=running or manifest["saved"]):
        store.update(run_id, saved=True)
        st.rerun()
    st.sidebar.caption(
        "Sau khi đóng trình duyệt, khôi phục hoặc xóa phiên đã giữ qua CLI trên máy này; xem hướng dẫn Saved runs trong README."
    )
    if st.sidebar.button("Xóa bản sao của phiên trong ứng dụng", disabled=running):
        store.delete(run_id)
        for state_key in ["run_id", "report", "request", "export_zip", "bi_plan"]:
            st.session_state.pop(state_key, None)
        st.rerun()
    st.sidebar.caption("Xóa phiên không xóa CSV nguồn, file đã tải xuống hoặc bản backup của máy.")
    validation = store.read(run_id, "validation_report.json")
    contract = BusinessContract.model_validate(st.session_state.contract)
    _render_validation_report(validation, contract)
    if validation["analysis_readiness"] != "ready":
        return
    st.subheader("2 · Đặt câu hỏi và chọn hai kỳ")
    local_mode = "Phân tích cục bộ bằng Python"
    unavailable_mode = "LLM agent — chưa bật trong ứng dụng"
    mode = st.radio(
        "Cách phân tích",
        [local_mode, unavailable_mode],
        help="Workflow deterministic chạy trên máy này và không gọi LLM.",
    )
    st.caption("LLM agent: Đã đánh giá riêng; chưa bật trong ứng dụng.")
    with st.form("analysis"):
        question = st.text_area(
            "Câu hỏi nghiệp vụ", "Doanh thu thay đổi thế nào và nhóm nào đóng góp nhiều nhất?"
        )
        cols = st.columns(4)
        previous_start = cols[0].date_input("Kỳ trước · từ", date(2026, 1, 1))
        previous_end = cols[1].date_input("Kỳ trước · đến, loại trừ", date(2026, 2, 1))
        current_start = cols[2].date_input("Kỳ hiện tại · từ", date(2026, 2, 1))
        current_end = cols[3].date_input("Kỳ hiện tại · đến, loại trừ", date(2026, 3, 1))
        launch = st.form_submit_button(
            "Chạy phân tích", type="primary", disabled=running or mode != local_mode
        )
    if launch:
        try:
            request = AnalysisRequest(
                question=question,
                metric_id="Revenue",
                previous=Period(start=previous_start, end=previous_end),
                current=Period(start=current_start, end=current_end),
                dimensions=list(contract.dimensions),
            )
            st.session_state.request = request.model_dump(mode="json")
            st.session_state.pop("report", None)
            st.session_state.pop("bi_plan", None)
            st.session_state.pop("export_zip", None)
            if mode == local_mode:
                with st.spinner("Đang tính và đối soát..."):
                    st.session_state.report = analyze_deterministic(run_id, store, request)
        except (BIError, ValidationError) as error:
            st.error(
                error.message
                if isinstance(error, BIError)
                else "Hai khoảng thời gian chưa hợp lệ hoặc đang chồng lặp."
            )
    if "report" in st.session_state:
        try:
            artifact_payload = store.read(run_id, "validated_analysis.json")
        except BIError:
            artifact_payload = None
        show_report(st.session_state.report, artifact_payload)
        st.subheader("3 · Chuyển sang Power BI")
        export_eligible = _can_export_report(st.session_state.report, artifact_payload)
        if not export_eligible:
            st.info(_export_unavailable_message(_validated_artifact(st.session_state.report, artifact_payload)))
        st.caption(
            "Gói project chứa dữ liệu của phạm vi phân tích. Chỉ lưu/chia sẻ với người có quyền xem dữ liệu."
        )
        st.caption("Bố cục Power BI dùng template cố định; không gửi câu hỏi chọn layout tới LLM.")
        if st.button("Tạo Power BI project", disabled=running or not export_eligible):
            try:
                dest = store._path(run_id) / ("powerbi_" + uuid.uuid4().hex[:8])
                request = AnalysisRequest.model_validate(st.session_state.request)
                export_powerbi(run_id, store, dest, request)
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                    for path in dest.rglob("*"):
                        if path.is_file():
                            archive.write(path, path.relative_to(dest).as_posix())
                st.session_state.export_zip = buffer.getvalue()
                st.success(
                    "Đã tạo project. Giải nén, mở EvidenceBI.pbip và Refresh trong Power BI Desktop."
                )
            except BIError as error:
                st.error(error.message)
        if "export_zip" in st.session_state:
            st.download_button(
                "Tải Power BI project (.zip)",
                st.session_state.export_zip,
                "EvidenceBI_PowerBI.zip",
                "application/zip",
            )
