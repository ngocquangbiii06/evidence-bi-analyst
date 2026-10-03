"""Power BI project export from verified computations, with explicit validation states."""

from __future__ import annotations

import base64
import json
import unicodedata
import uuid
from datetime import date, timedelta
from pathlib import Path

from pydantic import ValidationError

from .analysis_finalizer import IMPLEMENTATION_VERSION, trusted_analysis_load_context
from .analysis_store import ValidatedAnalysisStore
from .analytics import Analytics
from .contracts import AnalysisRequest, ValidatedAnalysisArtifact, canonical, fingerprint
from .data import minor_units, parse_date
from .errors import BIError
from .provider import INSTRUCTIONS, Action, strict_schema
from .store import RunStore, atomic_bytes
from .workflow import open_engine

MS = "https://developer.microsoft.com/json-schemas/"


def _pbir_id(value: str) -> str:
    """Stable Desktop-style identifier for PBIR page and visual folders."""
    return fingerprint({"pbir_id": value})[:20]


def _json(path: Path, data: dict | list):
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_bytes(
        path, (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    )


def _m_text(value: str) -> str:
    return '"' + value.replace('"', '""').replace("#(", "#(#)(") + '"'


def _table(name: str, columns: list[tuple[str, str]], rows: list[list], *, measures=None):
    # Values are data, encoded separately from M source. Text cannot inject an M expression.
    encoded = base64.b64encode(canonical(rows).encode()).decode()
    m_types = {"string": "type text", "int64": "Int64.Type", "dateTime": "type date"}
    names = "{" + ", ".join(_m_text(c) for c, _ in columns) + "}"
    types = "{" + ", ".join("{" + _m_text(c) + ", " + m_types[t] + "}" for c, t in columns) + "}"
    expression = [
        "let",
        f'    Rows = Json.Document(Binary.FromText("{encoded}", BinaryEncoding.Base64)),',
        f"    Source = Table.FromRows(Rows, {names}),",
        f'    Typed = Table.TransformColumnTypes(Source, {types}, "en-US")',
        "in",
        "    Typed",
    ]
    column_defs = [
        {"name": c, "dataType": t, "sourceColumn": c, "summarizeBy": "none"} for c, t in columns
    ]
    for column in column_defs:
        if column["dataType"] == "dateTime":
            column["formatString"] = "yyyy-MM-dd"
        if column["name"].endswith("Key") or column["name"].endswith("Minor"):
            column["isHidden"] = True
    result = {
        "name": name,
        "columns": column_defs,
        "partitions": [
            {"name": name, "mode": "import", "source": {"type": "m", "expression": expression}}
        ],
    }
    if measures:
        result["measures"] = measures
    return result


def _display_value(value) -> str:
    if value is None:
        return "(Thiếu giá trị)"
    if value == "":
        return "(Chuỗi rỗng)"
    return str(value)


def _display_filters(filters: dict[str, list[str | None]]) -> str:
    if not filters:
        return "Tất cả trong phạm vi dữ liệu đã xuất"
    return "; ".join(
        f"{_display_value(dimension)} = "
        + ", ".join(_display_value(value) for value in values)
        for dimension, values in sorted(filters.items())
    )


def _scope_label(scope, *, group_label=None, is_root=False) -> str:
    parts = [
        f"Chỉ số: {_display_value(scope.metric_id)} | Đơn vị: {_display_value(scope.unit)} "
        f"| Scale: {scope.scale}",
        f"Kỳ trước: [{scope.previous.start}, {scope.previous.end})",
        f"Kỳ hiện tại: [{scope.current.start}, {scope.current.end})",
        f"Bộ lọc: {_display_filters(scope.filters)}",
        "Phạm vi gốc" if is_root else "Phạm vi finding đã xác thực",
    ]
    if scope.dimension is not None:
        parts.append(
            f"Nhóm: {_display_value(scope.dimension)} = {_display_value(group_label)}"
        )
    return "\n".join(parts)


def _dax_date(value: date) -> str:
    return f"DATE({value.year}, {value.month}, {value.day})"


def _measures(engine: Analytics, request: AnalysisRequest) -> list[dict]:
    metric = engine.contract.metric(request.metric_id)
    identifier = metric.id
    base = f"SUM('FactSales'[{identifier}Minor])"
    if metric.scale:
        base = f"DIVIDE({base}, {10**metric.scale})"
    definitions = [(identifier, base, "#,0" + ("." + "0" * metric.scale if metric.scale else ""))]
    for title, period in [
        ("Previous Period", request.previous),
        ("Current Period", request.current),
    ]:
        period_filter = f"REMOVEFILTERS('DimDate'), FILTER(ALL('DimDate'), 'DimDate'[Date] >= {_dax_date(period.start)} && 'DimDate'[Date] < {_dax_date(period.end)})"
        value = f"CALCULATE([{identifier}], {period_filter})"
        if engine._covered(period):
            # No rows in a fully covered period is a known zero. Rows whose metric
            # is entirely null remain BLANK, matching the Python evidence semantics.
            value = f"VAR PeriodRows = CALCULATE(COUNTROWS('FactSales'), {period_filter})\nVAR Amount = {value}\nRETURN IF(COALESCE(PeriodRows, 0) = 0, 0, Amount)"
        definitions.append((f"{identifier} {title}", value, definitions[0][2]))
    definitions.extend(
        [
            (
                f"{identifier} Change",
                f"VAR Previous = [{identifier} Previous Period]\nVAR CurrentAmount = [{identifier} Current Period]\nRETURN IF(ISBLANK(Previous) || ISBLANK(CurrentAmount), BLANK(), CurrentAmount - Previous)",
                definitions[0][2],
            ),
            (
                f"{identifier} Growth %",
                f"VAR Previous = [{identifier} Previous Period]\nRETURN IF(Previous > 0, DIVIDE([{identifier} Change], Previous), BLANK())",
                "0.0%;-0.0%;0.0%",
            ),
        ]
    )
    return [
        {"name": n, "expression": v, "formatString": fmt, "displayFolder": "Business KPIs"}
        for n, v, fmt in definitions
    ]


def _trusted_export_calls(
    run_id: str,
    store: RunStore,
    engine: Analytics,
    policy,
    request: AnalysisRequest,
    artifact: ValidatedAnalysisArtifact,
) -> tuple[dict, dict]:
    manifest = store.manifest(run_id)
    if manifest.get("analysis_mode") != artifact.mode:
        raise BIError("STALE_ARTIFACT", "Analysis mode no longer matches the stored run.")

    if artifact.mode == "deterministic":
        try:
            state = store.read(run_id, "deterministic_execution.json")
        except BIError:
            raise BIError(
                "STALE_ARTIFACT", "Trusted deterministic execution record is missing."
            ) from None
        expected_snapshot = {
            "dataset": engine.dataset.sha256,
            "contract": fingerprint(engine.contract),
            "policy": fingerprint(policy),
            "request": fingerprint(request),
            "implementation_version": IMPLEMENTATION_VERSION,
        }
        if (
            not isinstance(state, dict)
            or fingerprint(state) != manifest.get("deterministic_execution_fingerprint")
            or state.get("schema_version") != "1.0"
            or state.get("run_id") != run_id
            or state.get("mode") != "deterministic"
            or state.get("status") != "COMPLETED"
            or state.get("snapshot") != expected_snapshot
        ):
            raise BIError(
                "STALE_ARTIFACT", "Trusted deterministic execution record is invalid."
            )
        evidence_calls = state.get("trusted_evidence_calls")
        results = state.get("results")
        if not isinstance(evidence_calls, dict) or not isinstance(results, list):
            raise BIError(
                "INVALID_ARTIFACT", "Trusted deterministic evidence registry is invalid."
            )
        return evidence_calls, _execution_evidence_registry(results, set(evidence_calls))

    if artifact.mode not in {"test_adapter", "live_agent"}:
        raise BIError("INVALID_ARTIFACT", "Analysis mode is not eligible for Power BI export.")
    try:
        state = store.read(run_id, "agent_state.json")
    except BIError:
        raise BIError(
            "STALE_ARTIFACT", "Trusted agent execution state is missing; rerun the analysis."
        ) from None
    if (
        not isinstance(state, dict)
        or fingerprint(state) != manifest.get("agent_state_fingerprint")
        or state.get("run_id") != run_id
        or state.get("status") != "COMPLETED"
    ):
        raise BIError(
            "STALE_ARTIFACT", "Trusted agent execution state is invalid or incomplete."
        )
    expected_snapshot = {
        "dataset": engine.dataset.sha256,
        "contract": fingerprint(engine.contract),
        "policy": fingerprint(policy),
        "request": fingerprint(request),
        "action_schema": fingerprint(strict_schema(Action)),
        "prompt": fingerprint({"instructions": INSTRUCTIONS}),
        "implementation_version": IMPLEMENTATION_VERSION,
    }
    snapshot = state.get("snapshot")
    if not isinstance(snapshot, dict) or any(
        snapshot.get(key) != value for key, value in expected_snapshot.items()
    ):
        raise BIError("STALE_ARTIFACT", "Trusted agent execution snapshot has changed.")
    evidence_calls = state.get("trusted_evidence_calls")
    conflicts = state.get("trusted_evidence_conflicts", [])
    results = state.get("results")
    if (
        not isinstance(evidence_calls, dict)
        or not isinstance(conflicts, list)
        or not isinstance(results, list)
    ):
        raise BIError("INVALID_ARTIFACT", "Trusted agent evidence-call registry is invalid.")
    trusted_calls = {key: value for key, value in evidence_calls.items() if key not in conflicts}
    return trusted_calls, _execution_evidence_registry(results, set(trusted_calls))


def _execution_evidence_registry(results: list, trusted_ids: set[str]) -> dict:
    registry = {}
    for result in results:
        if not isinstance(result, dict):
            raise BIError("INVALID_ARTIFACT", "Trusted execution evidence result is invalid.")
        evidence_id = result.get("evidence_id")
        if not isinstance(evidence_id, str) or evidence_id not in trusted_ids:
            continue
        existing = registry.get(evidence_id)
        if existing is not None and canonical(existing) != canonical(result):
            raise BIError("INVALID_ARTIFACT", "Trusted execution contains conflicting evidence.")
        registry[evidence_id] = result
    if set(registry) != trusted_ids:
        raise BIError("INVALID_ARTIFACT", "Trusted execution evidence does not resolve every call.")
    return registry


def _load_export_artifact(
    run_id: str,
    store: RunStore,
    engine: Analytics,
    policy,
    request: AnalysisRequest,
) -> ValidatedAnalysisArtifact:
    try:
        payload = store.read(run_id, "validated_analysis.json")
        hint = ValidatedAnalysisArtifact.model_validate(payload)
    except BIError:
        raise
    except (ValidationError, TypeError, ValueError):
        raise BIError(
            "INVALID_ARTIFACT", "Validated analysis artifact is missing or invalid."
        ) from None
    if hint.execution_status != "succeeded" or hint.sufficiency_status != "completed":
        raise BIError(
            "EXPORT_NOT_ELIGIBLE",
            "Power BI export requires a succeeded analysis with completed sufficiency.",
        )
    evidence_calls, execution_evidence = _trusted_export_calls(
        run_id, store, engine, policy, request, hint
    )
    load_context = trusted_analysis_load_context(
        engine.dataset.sha256, engine.contract, request, evidence_calls
    )
    artifact = ValidatedAnalysisStore(store).load(run_id, load_context)
    if canonical(artifact.evidence_registry) != canonical(execution_evidence):
        raise BIError(
            "TAMPERED_ARTIFACT",
            "Analysis evidence does not match the independently pinned execution results.",
        )
    if artifact.execution_status != "succeeded" or artifact.sufficiency_status != "completed":
        raise BIError(
            "EXPORT_NOT_ELIGIBLE",
            "Power BI export requires a succeeded analysis with completed sufficiency.",
        )
    return artifact


def build_model(
    engine: Analytics,
    request: AnalysisRequest,
    *,
    artifact: ValidatedAnalysisArtifact | None = None,
) -> tuple[dict, dict]:
    contract = engine.contract
    metric = engine._prepare(request.metric_id)
    mask = engine._mask(request.previous, request.filters) | engine._mask(
        request.current, request.filters
    )
    selected = engine.dataset.frame.loc[mask]
    dimensions = list(dict.fromkeys(request.dimensions + list(request.filters)))
    if "date" in {d.casefold() for d in dimensions} or len(
        {d.casefold() for d in dimensions}
    ) != len(dimensions):
        raise BIError(
            "PBI_NAME_COLLISION",
            "Dimension names conflict with Power BI's case-insensitive model catalog or reserved Date table.",
        )
    tables = []
    relationships = []
    mapping = {}
    for dimension in dimensions:
        column = contract.dimensions[dimension]
        values = {None if v in contract.null_tokens else v for v in selected[column]}
        ordered = sorted(values, key=lambda v: (v is not None, v or ""))
        folded = [
            "".join(
                c
                for c in unicodedata.normalize("NFKD", value).casefold().rstrip()
                if not unicodedata.combining(c)
            )
            for value in ordered
            if value is not None
        ]
        if len(set(folded)) != len(folded):
            raise BIError(
                "PBI_LABEL_COLLISION",
                "Distinct source labels may merge under Power BI text collation; confirm a normalization before export.",
            )
        mapping[dimension] = {value: index + 1 for index, value in enumerate(ordered)}
        missing_label = "(Missing value)"
        while missing_label in values:
            missing_label = "_" + missing_label
        rows = [
            [str(mapping[dimension][value]), missing_label if value is None else value]
            for value in ordered
        ]
        tables.append(
            _table("Dim" + dimension, [(dimension + "Key", "int64"), (dimension, "string")], rows)
        )
        relationships.append(
            {
                "name": "rel_" + dimension,
                "fromTable": "FactSales",
                "fromColumn": dimension + "Key",
                "toTable": "Dim" + dimension,
                "toColumn": dimension + "Key",
                "crossFilteringBehavior": "oneDirection",
            }
        )
    minimum = min(request.previous.start, request.current.start)
    maximum = max(request.previous.end, request.current.end) - timedelta(days=1)
    if maximum.year >= 9999 or maximum.year - minimum.year >= 10:
        raise BIError(
            "PBI_DATE_RANGE_LIMIT",
            "This export supports at most ten calendar years and dates before year 9999.",
        )
    moment = date(minimum.year, 1, 1)
    end = date(maximum.year + 1, 1, 1)
    dates = []
    while moment < end:
        dates.append(
            [
                moment.isoformat(),
                str(moment.year),
                moment.strftime("%Y-%m"),
                str(moment.year * 100 + moment.month),
            ]
        )
        moment += timedelta(days=1)
    date_table = _table(
        "DimDate",
        [("Date", "dateTime"), ("Year", "int64"), ("Month", "string"), ("MonthKey", "int64")],
        dates,
    )
    date_table["dataCategory"] = "Time"
    date_table["columns"][0]["isKey"] = True
    date_table["columns"][2]["sortByColumn"] = "MonthKey"
    tables.append(date_table)
    relationships.append(
        {
            "name": "rel_Date",
            "fromTable": "FactSales",
            "fromColumn": "Date",
            "toTable": "DimDate",
            "toColumn": "Date",
            "crossFilteringBehavior": "oneDirection",
        }
    )
    fact_columns = (
        [("LineID", "string"), ("Date", "dateTime")]
        + [(d + "Key", "int64") for d in dimensions]
        + [(metric.id + "Minor", "int64")]
    )
    fact_rows = []
    for index, row in selected.iterrows():
        source_value = row[metric.column]
        amount = (
            None
            if source_value in contract.null_tokens
            else str(minor_units(source_value, metric.scale))
        )
        keys = [
            str(
                mapping[d][
                    None
                    if row[contract.dimensions[d]] in contract.null_tokens
                    else row[contract.dimensions[d]]
                ]
            )
            for d in dimensions
        ]
        fact_rows.append(
            [
                str(index),
                parse_date(row[contract.date_column], contract.date_format).isoformat(),
                *keys,
                amount,
            ]
        )
    measures = _measures(engine, request)
    tables.insert(0, _table("FactSales", fact_columns, fact_rows, measures=measures))
    accepted_findings = (
        [record for record in artifact.findings if record.validation.accepted]
        if artifact is not None
        else []
    )
    evidence_rows = [
        [
            record.candidate.finding_id,
            record.candidate.claim_type,
            record.candidate.text,
            _scope_label(
                record.candidate.scope,
                group_label=record.candidate.label,
                is_root=canonical(record.candidate.scope)
                == canonical(artifact.root_scope),
            ),
            record.candidate.evidence_id,
            canonical(record.candidate.scope.model_dump(mode="json")),
            canonical(record.validation.model_dump(mode="json")),
            "accepted",
        ]
        for record in accepted_findings
    ]
    tables.append(
        _table(
            "Evidence",
            [
                ("FindingID", "string"),
                ("ClaimType", "string"),
                ("Finding", "string"),
                ("ScopeLabel", "string"),
                ("EvidenceID", "string"),
                ("ScopeJSON", "string"),
                ("ValidationJSON", "string"),
                ("Status", "string"),
            ],
            evidence_rows,
        )
    )
    info_rows = [
        ["Dataset", engine.dataset.sha256],
        ["Coverage", "Confirmed" if contract.coverage_confirmed else "Unknown"],
        ["Previous", f"{request.previous.start} to {request.previous.end} (exclusive)"],
        ["Current", f"{request.current.start} to {request.current.end} (exclusive)"],
        ["Scope", "Only selected periods and user filters are exported."],
        ["Interpretation", "Observed contributions do not establish external causality."],
    ]
    if artifact is not None:
        info_rows.extend(
            [
                ["Validated analysis fingerprint", artifact.content_fingerprint],
                ["Analysis sufficiency", artifact.sufficiency_status or "not_completed"],
                ["Root analysis scope", canonical(artifact.root_scope)],
                *[["Analysis limitation", limitation] for limitation in artifact.limitations],
            ]
        )
    tables.append(_table("AnalysisInfo", [("Property", "string"), ("Value", "string")], info_rows))
    model = {
        "name": "EvidenceBI",
        "compatibilityLevel": 1601,
        "model": {
            "culture": "en-US",
            "defaultPowerBIDataSourceVersion": "powerBI_V3",
            "sourceQueryCulture": "en-US",
            "tables": tables,
            "relationships": relationships,
            "annotations": [
                {"name": "PBI_QueryOrder", "value": json.dumps([t["name"] for t in tables])}
            ],
        },
    }
    spec = {
        "schema_version": "1.0",
        "method": "deterministic_verified_templates",
        "dataset_hash": engine.dataset.sha256,
        "contract_fingerprint": fingerprint(contract),
        "request": request.model_dump(mode="json"),
        "analysis_artifact": (
            {
                "fingerprint": artifact.content_fingerprint,
                "sufficiency_status": artifact.sufficiency_status,
                "root_scope": artifact.root_scope.model_dump(mode="json"),
                "accepted_finding_ids": artifact.accepted_finding_ids,
                "accepted_evidence_ids": sorted(
                    {record.candidate.evidence_id for record in accepted_findings}
                ),
                "limitations": list(artifact.limitations),
            }
            if artifact is not None
            else None
        ),
        "exported_rows": len(fact_rows),
        "kpis": [
            {
                "name": m["name"],
                "dax": m["expression"],
                "validation": {
                    "references": "passed",
                    "syntax": "not_checked",
                    "execution": "not_checked",
                    "reconciliation": "not_checked",
                },
            }
            for m in measures
        ],
        "model": {
            "grain": contract.grain_description,
            "tables": [
                {"name": t["name"], "columns": [c["name"] for c in t["columns"]]} for t in tables
            ],
            "relationships": relationships,
        },
        "limitations": [
            "DAX must be executed in Power BI before execution/reconciliation can be marked passed.",
            "LLM-selected report layout is excluded; the flagship uses fixed deterministic visuals.",
            *(
                ["Analysis: " + limitation for limitation in artifact.limitations]
                if artifact is not None
                else []
            ),
        ],
    }
    return model, spec


def _projection(table, field, *, measure=False, format=None):
    kind = "Measure" if measure else "Column"
    projection = {
        "field": {kind: {"Expression": {"SourceRef": {"Entity": table}}, "Property": field}},
        "queryRef": f"{table}.{field}",
        "nativeQueryRef": field,
    }
    if format is not None:
        projection["format"] = format
    return projection


def _literal(value):
    if isinstance(value, bool):
        raw = "true" if value else "false"
    elif isinstance(value, (int, float)):
        raw = str(value) + "D"
    else:
        raw = "'" + str(value).replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": raw}}}


def _fill(color: str) -> dict:
    return {"solid": {"color": _literal(color)}}


def _signed_fill(measure: str) -> dict:
    """Return a native PBIR FillRule for signed change values.

    The zero midpoint is intentionally neutral so negative/positive bars remain
    distinguishable without adding a presentation-only DAX measure.
    """
    return {
        "solid": {
            "color": {
                "expr": {
                    "FillRule": {
                        "Input": {
                            "Measure": {
                                "Expression": {"SourceRef": {"Entity": "FactSales"}},
                                "Property": measure,
                            }
                        },
                        "FillRule": {
                            "linearGradient3": {
                                "min": {
                                    "color": {"Literal": {"Value": "'#B54734'"}},
                                    "value": {"Literal": {"Value": "-1D"}},
                                },
                                "mid": {
                                    "color": {"Literal": {"Value": "'#64748B'"}},
                                    "value": {"Literal": {"Value": "0D"}},
                                },
                                "max": {
                                    "color": {"Literal": {"Value": "'#087F72'"}},
                                    "value": {"Literal": {"Value": "1D"}},
                                },
                            }
                        },
                    }
                }
            }
        }
    }


def _scope_technical_rows_filter() -> dict:
    """Hide implementation metadata from the reader-facing scope table."""
    technical_rows = [
        "Dataset",
        "Validated analysis fingerprint",
        "Root analysis scope",
    ]
    return {
        "name": _pbir_id("filter:evidence:scope-technical-rows"),
        "field": {
            "Column": {
                "Expression": {"SourceRef": {"Entity": "AnalysisInfo"}},
                "Property": "Property",
            }
        },
        "type": "Categorical",
        "filter": {
            "Version": 2,
            "From": [{"Name": "a", "Entity": "AnalysisInfo", "Type": 0}],
            "Where": [
                {
                    "Condition": {
                        "Not": {
                            "Expression": {
                                "In": {
                                    "Expressions": [
                                        {
                                            "Column": {
                                                "Expression": {"SourceRef": {"Source": "a"}},
                                                "Property": "Property",
                                            }
                                        }
                                    ],
                                    "Values": [
                                        [{"Literal": {"Value": f"'{value}'"}}]
                                        for value in technical_rows
                                    ],
                                }
                            }
                        }
                    }
                }
            ],
        },
        "howCreated": "User",
        "isHiddenInViewMode": True,
        "isLockedInViewMode": True,
        # Desktop persists inverted basic-filter selections as card state in
        # addition to the Not/In predicate.  Without it, a hand-authored
        # PBIR visual can render the unfiltered table despite a valid filter.
        "objects": {
            "general": [
                {
                    "properties": {
                        "isInvertedSelectionMode": _literal(True),
                    }
                }
            ]
        },
    }


def _format_pattern(scale: int, *, signed=False) -> str:
    number = "#,0" + ("." + "0" * scale if scale else "")
    return f"+{number};-{number};{number}" if signed else number


def _visual(name, kind, title, x, y, width, height, roles, *, objects=None):
    visual = {
        "visualType": kind,
        "query": {
            "queryState": {role: {"projections": fields} for role, fields in roles.items()}
        },
        "visualContainerObjects": {
            "title": [
                {
                    "properties": {
                        "show": _literal(True),
                        "text": _literal(title),
                        "fontSize": _literal(14),
                        "fontColor": _fill("#142D4E"),
                    }
                }
            ],
            "background": [
                {
                    "properties": {
                        "show": _literal(True),
                        "color": _fill("#FFFFFF"),
                        "transparency": _literal(0),
                    }
                }
            ],
            "border": [
                {
                    "properties": {
                        "show": _literal(True),
                        "color": _fill("#D9E2EC"),
                        "radius": _literal(8),
                        "width": _literal(1),
                    }
                }
            ],
        },
        "drillFilterOtherVisuals": False,
    }
    if objects:
        visual["objects"] = objects
    return {
        "$schema": MS + "fabric/item/report/definition/visualContainer/2.1.0/schema.json",
        "name": name,
        "position": {"x": x, "y": y, "z": 0, "height": height, "width": width, "tabOrder": 0},
        "visual": visual,
    }


def _textbox(name, x, y, width, height, paragraphs, *, background="#FFFFFF"):
    return {
        "$schema": MS + "fabric/item/report/definition/visualContainer/2.1.0/schema.json",
        "name": name,
        "position": {"x": x, "y": y, "z": 0, "height": height, "width": width, "tabOrder": 0},
        "visual": {
            "visualType": "textbox",
            "objects": {
                "general": [
                    {
                        "properties": {
                            "paragraphs": [
                                {
                                    "textRuns": [
                                        {
                                            "value": text,
                                            "textStyle": {
                                                "fontFamily": "Segoe UI",
                                                "fontSize": font_size,
                                                "fontWeight": "bold" if bold else "normal",
                                                "color": color,
                                            },
                                        }
                                    ],
                                    "horizontalTextAlignment": "left",
                                }
                                for text, font_size, bold, color in paragraphs
                            ]
                        }
                    }
                ]
            },
            "visualContainerObjects": {
                "title": [{"properties": {"show": _literal(False)}}],
                "background": [
                    {
                        "properties": {
                            "show": _literal(True),
                            "color": _fill(background),
                            "transparency": _literal(0),
                        }
                    }
                ],
                "border": [
                    {
                        "properties": {
                            "show": _literal(True),
                            "color": _fill("#D9E2EC"),
                            "radius": _literal(8),
                            "width": _literal(1),
                        }
                    }
                ],
            },
            "drillFilterOtherVisuals": False,
        },
    }


def build_report(
    request: AnalysisRequest,
    *,
    artifact: ValidatedAnalysisArtifact | None = None,
    dataset_class: str | None = None,
) -> dict[str, dict]:
    documents = {}
    documents["definition/version.json"] = {
        "$schema": MS + "fabric/item/report/definition/versionMetadata/1.0.0/schema.json",
        "version": "2.0.0",
    }
    documents["definition/report.json"] = {
        "$schema": MS + "fabric/item/report/definition/report/3.0.0/schema.json",
        "themeCollection": {},
    }
    page_ids = {
        "overview": _pbir_id("page:overview"),
        "evidence": _pbir_id("page:evidence"),
    }
    documents["definition/pages/pages.json"] = {
        "$schema": MS + "fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": [page_ids["overview"], page_ids["evidence"]],
        "activePageName": page_ids["overview"],
    }
    page_titles = {
        "overview": "Tổng quan doanh thu",
        "evidence": "Bằng chứng và phạm vi",
    }
    for name in ("overview", "evidence"):
        page_id = page_ids[name]
        documents[f"definition/pages/{page_id}/page.json"] = {
            "$schema": MS + "fabric/item/report/definition/page/2.0.0/schema.json",
            "name": page_id,
            "displayName": page_titles[name],
            "displayOption": "FitToPage",
            "width": 1280,
            "height": 800,
        }
    metric = request.metric_id
    unit = artifact.root_scope.unit if artifact is not None else ""
    scale = artifact.root_scope.scale if artifact is not None else 0
    root_filters = (
        artifact.root_scope.filters if artifact is not None else request.filters
    )
    header_detail = (
        f"Kỳ trước [{request.previous.start}, {request.previous.end}) · "
        f"Kỳ hiện tại [{request.current.start}, {request.current.end}) · "
        f"Đơn vị {unit or 'theo contract'}, scale {scale} · "
        f"Dữ liệu {dataset_class or 'đã xác thực'} · Bộ lọc: {_display_filters(root_filters)}"
    )
    header = _textbox(
        "T01",
        24,
        16,
        1232,
        80,
        [
            ("Tổng quan doanh thu", "22pt", True, "#142D4E"),
            (header_detail, "10pt", False, "#334155"),
        ],
    )
    header_id = _pbir_id("visual:overview:t01-header")
    header["name"] = header_id
    documents[f"definition/pages/{page_ids['overview']}/visuals/{header_id}/visual.json"] = (
        header
    )
    visuals = []
    card_specs = [
        ("Previous Period", "Kỳ trước", False, None),
        ("Current Period", "Kỳ hiện tại", False, None),
        ("Change", "Chênh lệch", True, _format_pattern(scale, signed=True)),
        ("Growth %", "Tăng trưởng", True, "+0.00%;-0.00%;0.00%"),
    ]
    for i, (suffix, title, _signed, custom_format) in enumerate(card_specs):
        value_properties = {
            "fontSize": _literal(30),
            "labelDisplayUnits": _literal("0"),
        }
        if custom_format is not None:
            value_properties["customFormatString"] = _literal(custom_format)
        projection_options = (
            {"format": custom_format}
            if suffix == "Growth %"
            else {"format": _format_pattern(scale, signed=True)}
            if suffix == "Change"
            else {}
        )
        visuals.append(
            _visual(
                "kpi" + str(i),
                "cardVisual",
                title + (f" ({unit})" if unit and suffix != "Growth %" else ""),
                24 + i * 312,
                116,
                296,
                116,
                {
                    "Data": [
                        _projection(
                            "FactSales",
                            metric + " " + suffix,
                            measure=True,
                            **projection_options,
                        )
                    ]
                },
                objects={
                    "value": [
                        {"selector": {"id": "default"}, "properties": value_properties}
                    ],
                    "label": [
                        {
                            "selector": {"id": "default"},
                            "properties": {"fontSize": _literal(11)},
                        }
                    ],
                },
            )
        )
    for i, dimension in enumerate(request.dimensions[:2]):
        x, y, w, h = (24, 252, 608, 268) if i == 0 else (648, 252, 608, 268)
        visuals.append(
            _visual(
                "breakdown" + str(i),
                "barChart",
                f"Chênh lệch {metric} theo {dimension}",
                x,
                y,
                w,
                h,
                {
                    "Category": [_projection("Dim" + dimension, dimension)],
                    "Y": [
                        _projection(
                            "FactSales",
                            metric + " Change",
                            measure=True,
                            format=_format_pattern(scale, signed=True),
                        )
                    ],
                },
                objects={
                    "labels": [
                        {
                            "properties": {
                                "show": _literal(True),
                                "labelDisplayUnits": _literal("0"),
                                "valueCustomFormatString": _literal(
                                    _format_pattern(scale, signed=True)
                                ),
                            }
                        }
                    ],
                    "dataPoint": [
                        {
                            "properties": {"fill": _signed_fill(metric + " Change")},
                            "selector": {
                                "data": [
                                    {"dataViewWildcard": {"matchingOption": 0}}
                                ]
                            },
                        }
                    ],
                },
            )
        )
    visuals.append(
        _visual(
            "trend",
            "columnChart",
            "Doanh thu quan sát theo tháng",
            24,
            540,
            448,
            236,
            {
                "Category": [_projection("DimDate", "Month")],
                "Y": [_projection("FactSales", metric, measure=True)],
            },
            objects={
                "labels": [
                    {
                        "properties": {
                            "show": _literal(True),
                            "labelDisplayUnits": _literal("0"),
                        }
                    }
                ],
                "dataPoint": [
                    {"properties": {"defaultColor": _fill("#087F72")}}
                ],
            },
        )
    )
    for visual in visuals:
        visual_id = _pbir_id("visual:overview:" + visual["name"])
        visual["name"] = visual_id
        documents[f"definition/pages/{page_ids['overview']}/visuals/{visual_id}/visual.json"] = (
            visual
        )
    root_evidence_ids = set(artifact.root_evidence_ids) if artifact is not None else set()
    accepted_findings = (
        [
            record
            for record in artifact.findings
            if record.validation.accepted
            and record.candidate.evidence_id in root_evidence_ids
        ]
        if artifact is not None
        else []
    )
    caveat_text = (
        "Giới hạn: các biến động và đóng góp quan sát được không chứng minh nguyên nhân."
    )
    if any(record.candidate.delta_minor < 0 for record in accepted_findings):
        caveat_text += " Cần kiểm tra thêm bối cảnh bán hàng ở các nhóm giảm."
    narrative_lines = [
        ("Nhận xét đã được xác thực", "16pt", True, "#142D4E"),
        *[
            (f"• {record.candidate.text}", "10pt", False, "#334155")
            for record in accepted_findings
        ],
        (
            caveat_text,
            "10pt",
            False,
            "#9A6700",
        ),
        (
            "Lưu ý chuỗi thời gian: mới quan sát hai kỳ dữ liệu, chưa đủ điều kiện kết luận xu hướng dài hạn.",
            "10pt",
            False,
            "#9A6700",
        ),
    ]
    narrative = _textbox("T02", 492, 540, 764, 236, narrative_lines)
    narrative_id = _pbir_id("visual:overview:t02-insights")
    narrative["name"] = narrative_id
    documents[
        f"definition/pages/{page_ids['overview']}/visuals/{narrative_id}/visual.json"
    ] = narrative

    overview_sources = [
        _pbir_id("visual:overview:breakdown" + str(i))
        for i in range(len(request.dimensions[:2]))
    ] + [_pbir_id("visual:overview:trend")]
    overview_targets = [
        _pbir_id("visual:overview:kpi" + str(i)) for i in range(4)
    ] + overview_sources + [narrative_id]
    visual_interactions = []
    for src_id in overview_sources:
        for tgt_id in overview_targets:
            if src_id != tgt_id:
                visual_interactions.append(
                    {"source": src_id, "target": tgt_id, "type": "NoFilter"}
                )
    documents[f"definition/pages/{page_ids['overview']}/page.json"]["visualInteractions"] = (
        visual_interactions
    )

    evidence_header = _textbox(
        "T03",
        24,
        16,
        1232,
        80,
        [
            ("Bằng chứng và phạm vi", "22pt", True, "#142D4E"),
            (
                "Phạm vi gốc thuộc lượt phân tích; mỗi finding giữ phạm vi đã xác thực riêng ở cột Phạm vi.",
                "10pt",
                False,
                "#334155",
            ),
        ],
    )
    evidence_header_id = _pbir_id("visual:evidence:t03-header")
    evidence_header["name"] = evidence_header_id
    documents[
        f"definition/pages/{page_ids['evidence']}/visuals/{evidence_header_id}/visual.json"
    ] = evidence_header

    table_objects = {
        "columnHeaders": [
            {"properties": {"wordWrap": _literal(True)}}
        ],
        "values": [
            {"properties": {"wordWrap": _literal(True)}}
        ],
    }
    table = _visual(
        "findings",
        "tableEx",
        "Finding đã được chấp nhận",
        24,
        116,
        796,
        536,
        {
            "Values": [
                _projection("Evidence", c)
                for c in ["FindingID", "Finding", "ScopeLabel", "Status"]
            ]
        },
        objects=table_objects,
    )
    table_id = _pbir_id("visual:evidence:findings")
    table["name"] = table_id
    documents[f"definition/pages/{page_ids['evidence']}/visuals/{table_id}/visual.json"] = table
    scope = _visual(
        "scope",
        "tableEx",
        "Phạm vi và giới hạn phân tích",
        840,
        116,
        416,
        536,
        {
            "Values": [
                _projection("AnalysisInfo", "Property"),
                _projection("AnalysisInfo", "Value"),
            ]
        },
        objects=table_objects,
    )
    scope["filterConfig"] = {"filters": [_scope_technical_rows_filter()]}
    scope_id = _pbir_id("visual:overview:scope")
    scope["name"] = scope_id
    documents[f"definition/pages/{page_ids['evidence']}/visuals/{scope_id}/visual.json"] = scope
    caveat = _textbox(
        "T04",
        24,
        672,
        1232,
        104,
        [
            ("Cách đọc bằng chứng", "14pt", True, "#142D4E"),
            (
                "Coverage là xác nhận về phạm vi dữ liệu được cung cấp, không phải bằng chứng nhân quả. "
                "ScopeJSON, ValidationJSON, EvidenceID và raw evidence vẫn được giữ trong evidence.json "
                "để đối chiếu ngoài báo cáo.",
                "10pt",
                False,
                "#334155",
            ),
        ],
    )
    caveat_id = _pbir_id("visual:evidence:t04-caveat")
    caveat["name"] = caveat_id
    documents[f"definition/pages/{page_ids['evidence']}/visuals/{caveat_id}/visual.json"] = (
        caveat
    )
    return documents


def export_powerbi(
    run_id: str, store: RunStore, output: Path, request: AnalysisRequest, *, use_plan=False
) -> dict:
    if use_plan:
        raise BIError(
            "BI_LAYOUT_DISABLED",
            "LLM-selected layout is outside the frozen flagship scope; use fixed report visuals.",
        )
    if output.exists() or output.is_symlink():
        raise BIError(
            "EXPORT_EXISTS",
            "Choose a new output directory; existing files will not be overwritten.",
        )
    engine, policy = open_engine(run_id, store)
    engine._prepare(request.metric_id)
    artifact = _load_export_artifact(run_id, store, engine, policy, request)
    model, spec = build_model(engine, request, artifact=artifact)
    documents = build_report(
        request,
        artifact=artifact,
        dataset_class=policy.dataset_class,
    )
    accepted_findings = [record for record in artifact.findings if record.validation.accepted]
    accepted_evidence_ids = list(
        dict.fromkeys(record.candidate.evidence_id for record in accepted_findings)
    )
    evidence_payload = {
        "schema_version": "1.0",
        "validated_analysis_fingerprint": artifact.content_fingerprint,
        "sufficiency_status": artifact.sufficiency_status,
        "dataset_hash": artifact.dataset_hash,
        "contract_fingerprint": artifact.contract_fingerprint,
        "root_scope": artifact.root_scope.model_dump(mode="json"),
        "limitations": list(artifact.limitations),
        "accepted_finding_ids": list(artifact.accepted_finding_ids),
        "accepted_evidence_ids": accepted_evidence_ids,
        "findings": [record.model_dump(mode="json") for record in accepted_findings],
        "evidence_registry": {
            evidence_id: artifact.evidence_registry[evidence_id]
            for evidence_id in accepted_evidence_ids
        },
    }
    try:
        output.mkdir(parents=True, mode=0o700)
        _json(
            output / "EvidenceBI.SemanticModel" / "definition.pbism",
            {
                "$schema": MS + "fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
                "version": "1.0",
                "settings": {},
            },
        )
        _json(output / "EvidenceBI.SemanticModel" / "model.bim", model)
        _json(
            output / "EvidenceBI.Report" / "definition.pbir",
            {
                "$schema": MS + "fabric/item/report/definitionProperties/2.0.0/schema.json",
                "version": "4.0",
                "datasetReference": {"byPath": {"path": "../EvidenceBI.SemanticModel"}},
            },
        )
        _json(
            output / "EvidenceBI.Report" / ".platform",
            {
                "$schema": MS + "fabric/gitIntegration/platformProperties/2.0.0/schema.json",
                "metadata": {"type": "Report", "displayName": "EvidenceBI"},
                "config": {"version": "2.0", "logicalId": str(uuid.UUID(run_id))},
            },
        )
        for name, document in documents.items():
            _json(output / "EvidenceBI.Report" / name, document)
        _json(
            output / "EvidenceBI.pbip",
            {
                "$schema": MS + "fabric/pbip/pbipProperties/1.0.0/schema.json",
                "version": "1.0",
                "artifacts": [{"report": {"path": "EvidenceBI.Report"}}],
                "settings": {"enableAutoRecovery": False},
            },
        )
        _json(output / "bi_spec.json", spec)
        _json(output / "evidence.json", evidence_payload)
        notes = """# Open in Power BI Desktop

This project contains embedded data for the selected analysis scope. Keep it private for confidential input.

1. Open EvidenceBI.pbip in Power BI Desktop (or EvidenceBI.Report/definition.pbir).
2. Refresh the model to load the embedded M partitions. No external CSV path or cloud connection is required.
3. Inspect Business performance and Evidence & scope.
4. Validate DAX results in the selected date/region/product/empty contexts before marking reconciliation passed.

Measures for Previous/Current Period use the explicit analysis periods and intentionally override date filters. Dimension filters still apply. The base metric follows the date context.

This artifact was generated by deterministic BI templates. Model execution and visual rendering have not been asserted by this file.
"""
        atomic_bytes(output / "README.md", notes.encode())
        _json(
            output / "export_manifest.json",
            {
                "schema_version": "1.0",
                "run_id": run_id,
                "dataset_hash": engine.dataset.sha256,
                "validated_analysis_fingerprint": artifact.content_fingerprint,
                "model_fingerprint": fingerprint(model),
                "policy_fingerprint": fingerprint(policy),
                "status": "generated_not_executed",
                "data_class": policy.dataset_class,
            },
        )
    except OSError:
        raise BIError("EXPORT_FAILED", "Export could not finish writing local files.") from None
    return {
        "output": str(output.resolve()),
        "project": str((output / "EvidenceBI.pbip").resolve()),
        "model_fingerprint": fingerprint(model),
    }
