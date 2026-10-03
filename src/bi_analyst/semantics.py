"""Local schema evidence and tentative mappings; a proposal never grants permission."""

from __future__ import annotations

import re

from .contracts import fingerprint
from .data import Dataset, minor_units, parse_date

DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"]


def schema_evidence(dataset: Dataset, *, sample_limit=5000) -> dict:
    columns = []
    for index, name in enumerate(dataset.frame.columns):
        values = dataset.frame[name]
        usable = values[values != ""]
        sample = usable.iloc[:sample_limit].tolist()
        formats = {}
        for fmt in DATE_FORMATS:
            valid = 0
            for value in sample:
                try:
                    parse_date(value, fmt)
                    valid += 1
                except ValueError:
                    pass
            formats[fmt] = valid
        numeric = 0
        for value in sample:
            try:
                minor_units(value, 4)
                numeric += 1
            except ValueError:
                pass
        body = {
            "column_token": f"c{index}",
            "name": name,
            "null_count": len(values) - len(usable),
            "unique_nonnull_count": int(usable.nunique()),
            "nonnull_count": len(usable),
            "type_scan": "first_nonempty_values",
            "sample_count": len(sample),
            "date_valid_counts": formats,
            "numeric_valid_count": numeric,
            "uniqueness_scan": "full",
        }
        columns.append(
            body | {"evidence_id": "SP_" + fingerprint({"dataset": dataset.sha256, **body})[:24]}
        )
    return {
        "schema_version": "1.0",
        "dataset_hash": dataset.sha256,
        "row_count": len(dataset.frame),
        "columns": columns,
        "null_definition": "Empty string only; confirm other null markers in the business contract.",
    }


def propose_semantics(dataset: Dataset) -> dict:
    profile = schema_evidence(dataset)
    columns = profile["columns"]
    unknowns = [
        "Confirm what one row represents; uniqueness does not prove business grain.",
        "Confirm whether revenue belongs to each line or is an order total repeated across lines.",
        "Confirm currency, decimal scale, returns and null-value treatment.",
        "Confirm complete coverage separately; observed date bounds do not prove completeness.",
    ]

    def normalized(column):
        return re.sub(r"[^a-z0-9]", "", column["name"].casefold())

    dates = [
        c
        for c in columns
        if c["sample_count"] and max(c["date_valid_counts"].values()) == c["sample_count"]
    ]
    preferred = [c for c in dates if normalized(c) in {"orderdate", "transactiondate", "salesdate"}]
    candidates = preferred or dates
    date_column = candidates[0] if len(candidates) == 1 else None
    formats = (
        [
            fmt
            for fmt, valid in date_column["date_valid_counts"].items()
            if valid == date_column["sample_count"]
        ]
        if date_column
        else []
    )
    date_format = formats[0] if len(formats) == 1 else None
    if not date_column or not date_format:
        unknowns.append("Date column or day/month order is ambiguous; choose explicitly.")
    metrics = [
        c
        for c in columns
        if normalized(c) in {"revenue", "netrevenue", "salesamount", "doanhthu"}
        and c["sample_count"]
        and c["numeric_valid_count"] == c["sample_count"]
    ]
    metric = metrics[0] if len(metrics) == 1 else None
    if metric is None:
        unknowns.append(
            "Revenue source is ambiguous; a numeric type alone does not establish an additive metric."
        )
    keys = [
        c
        for c in columns
        if normalized(c) in {"lineid", "orderlineid", "transactionlineid"}
        and c["null_count"] == 0
        and c["unique_nonnull_count"] == profile["row_count"]
        and profile["row_count"]
    ]
    key = keys[0] if len(keys) == 1 else None
    if key is None:
        unknowns.append(
            "No unambiguous line key found; review a composite key or confirm the duplicate policy."
        )
    dimensions = [
        c
        for c in columns
        if normalized(c)
        in {"region", "product", "category", "channel", "segment", "khuvuc", "sanpham"}
        and c["unique_nonnull_count"] <= 1000
    ]
    chosen = [c for c in [date_column, metric, key, *dimensions] if c]
    return {
        "schema_version": "1.0",
        "method": "local_rules_with_profile_evidence",
        "confirmed": False,
        "dataset_hash": dataset.sha256,
        "mappings": {
            "date_column": date_column["name"] if date_column else None,
            "date_format": date_format,
            "row_key_columns": [key["name"]] if key else [],
            "metric_column": metric["name"] if metric else None,
            "dimension_columns": [c["name"] for c in dimensions],
        },
        "evidence_ids": list(dict.fromkeys(c["evidence_id"] for c in chosen)),
        "unknowns": unknowns,
        "profile": profile,
    }
