"""Bounded CSV ingestion, exact money parsing and deterministic profiling."""

from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import stat
import threading
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

import pandas as pd

from .contracts import (
    BusinessContract,
    DataPolicy,
    Issue,
    ParserConfig,
    ValidationReport,
    fingerprint,
)
from .errors import BIError

MAX_INT = 2**63 - 1
CSV_LOCK = threading.Lock()  # csv.field_size_limit is process-global


@dataclass
class Dataset:
    frame: pd.DataFrame
    sha256: str
    dataset_id: str
    byte_count: int
    parser: ParserConfig
    raw: bytes


def load_csv(path: Path, policy: DataPolicy, parser: ParserConfig | None = None) -> Dataset:
    return load_csv_bytes(read_csv_bytes(path, policy), policy, parser)


def read_csv_bytes(path: Path, policy: DataPolicy) -> bytes:
    path = Path(path)
    if path.suffix.lower() != ".csv" or path.is_symlink():
        raise BIError("UNSUPPORTED_FILE", "Provide a regular, uncompressed CSV file.")
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise BIError("UNSUPPORTED_FILE", "Input must be a regular file.")
        if info.st_size > policy.max_file_bytes:
            raise BIError("FILE_LIMIT", "Input exceeds the configured byte limit.")
        with os.fdopen(fd, "rb") as stream:
            fd = None
            content = stream.read(policy.max_file_bytes + 1)
        if len(content) > policy.max_file_bytes:
            raise BIError("FILE_LIMIT", "Input exceeds the configured byte limit.")
    except OSError:
        raise BIError("FILE_READ_ERROR", "Input cannot be read safely.") from None
    finally:
        if fd is not None:
            os.close(fd)
    return content


def load_csv_bytes(
    content: bytes, policy: DataPolicy, parser: ParserConfig | None = None
) -> Dataset:
    parser = parser or ParserConfig()
    if len(content) > policy.max_file_bytes:
        raise BIError("FILE_LIMIT", "Input exceeds the configured byte limit.")
    if not content:
        raise BIError("EMPTY_DATASET", "The CSV file is empty.")
    try:
        decoded = content.decode(parser.encoding)
    except UnicodeDecodeError:
        raise BIError("ENCODING_ERROR", "Input must use the configured UTF-8 encoding.") from None
    if "\x00" in decoded:
        raise BIError("BINARY_CONTENT", "CSV contains an unsupported binary character.")
    rows = []
    with CSV_LOCK:
        old_limit = csv.field_size_limit(policy.max_cell_chars)
        try:
            reader = csv.reader(
                io.StringIO(decoded, newline=""), delimiter=parser.delimiter, strict=True
            )
            headers = next(reader, None)
            if not headers:
                raise BIError("EMPTY_DATASET", "CSV has no header.")
            if len(headers) > policy.max_columns:
                raise BIError("COLUMN_LIMIT", "CSV exceeds the configured column limit.")
            if len(headers) != len(set(headers)) or any(not h.strip() for h in headers):
                raise BIError("INVALID_HEADER", "CSV column names must be nonempty and unique.")
            if any(len(h) > 128 for h in headers):
                raise BIError("INVALID_HEADER", "CSV column names exceed the supported length.")
            for row in reader:
                if len(rows) >= policy.max_rows:
                    raise BIError("ROW_LIMIT", "CSV exceeds the configured row limit.")
                if len(row) != len(headers):
                    raise BIError("MALFORMED_CSV", "CSV contains an inconsistent field count.")
                if any(len(value) > policy.max_cell_chars for value in row):
                    raise BIError("CELL_LIMIT", "CSV exceeds the configured cell limit.")
                rows.append(row)
        except csv.Error:
            raise BIError(
                "MALFORMED_CSV", "CSV is malformed or a field exceeds its limit."
            ) from None
        finally:
            csv.field_size_limit(old_limit)
    sha256 = hashlib.sha256(content).hexdigest()
    return Dataset(
        pd.DataFrame(rows, columns=headers, dtype="string"),
        sha256,
        fingerprint({"hash": sha256, "parser": parser.model_dump()})[:24],
        len(content),
        parser,
        content,
    )


def minor_units(value: str, scale: int) -> int:
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value):
        raise ValueError("Invalid decimal literal")
    try:
        with localcontext() as context:
            context.prec = max(32, len(value) + scale + 4)
            number = Decimal(value) * (10**scale)
            if not number.is_finite() or number != number.to_integral_value():
                raise ValueError("Unsupported precision")
            if abs(number) > MAX_INT:
                raise ValueError("Money exceeds fixed-point range")
            return int(number)
    except InvalidOperation:
        raise ValueError("Invalid decimal literal") from None


def money(value: int | None, scale: int) -> str | None:
    if value is None:
        return None
    with localcontext() as context:
        context.prec = 40
        return format(Decimal(value).scaleb(-scale), f".{scale}f")


def parse_date(value: str, fmt: str):
    # Parse only the three declared formats; strptime is costly on repeated full scans.
    if len(value) != 10 or not value.replace("-", "").replace("/", "").isascii():
        raise ValueError("Date must match the declared format exactly")
    if fmt == "%Y-%m-%d":
        if value[4] != "-" or value[7] != "-":
            raise ValueError("Date must match the declared format exactly")
        return date.fromisoformat(value)
    if fmt not in {"%d/%m/%Y", "%m/%d/%Y"} or value[2] != "/" or value[5] != "/":
        raise ValueError("Date must match the declared format exactly")
    first, second, year = value[:2], value[3:5], value[6:]
    if not (first + second + year).isdigit():
        raise ValueError("Invalid date components")
    day, month = (first, second) if fmt == "%d/%m/%Y" else (second, first)
    return date(int(year), int(month), int(day))


def duplicate_counts(values: list[tuple]) -> dict:
    counts = Counter(values)
    repeated = [n for n in counts.values() if n > 1]
    return {
        "duplicated_groups": len(repeated),
        "involved_rows": sum(repeated),
        "excess_rows": sum(n - 1 for n in repeated),
    }


def profile_dataset(dataset: Dataset, contract: BusinessContract) -> tuple[dict, ValidationReport]:
    df = dataset.frame
    issues: list[Issue] = []

    def issue(code, scope, message, count=1, severity="error"):
        issues.append(
            Issue(code=code, severity=severity, scope=scope, count=count, message=message)
        )

    if not len(df):
        issue("NO_DATA", "dataset", "Dataset contains no records.")
    if not contract.confirmed:
        issue("SEMANTICS_UNCONFIRMED", "contract", "Business semantics require confirmation.")
    elif (
        not contract.grain_description.strip()
        or not contract.date_column.strip()
        or not any(metric.id == "Revenue" for metric in contract.metrics)
    ):
        issue(
            "SEMANTICS_INCOMPLETE",
            "contract",
            "Confirmed semantics require a grain, date mapping and additive Revenue mapping.",
        )
    required = {contract.date_column, *contract.row_key_columns, *contract.dimensions.values()}
    required.update(m.column for m in contract.metrics)
    if contract.currency_column:
        required.add(contract.currency_column)
    missing = required - set(df.columns)
    if missing:
        issue("MISSING_COLUMNS", "contract", "Required columns are missing.", len(missing))
    full_duplicates = duplicate_counts(list(df.itertuples(index=False, name=None)))
    keys = None
    if contract.row_key_columns and all(c in df for c in contract.row_key_columns):
        key_rows = list(df[contract.row_key_columns].itertuples(index=False, name=None))
        null_keys = sum(any(v in contract.null_tokens for v in row) for row in key_rows)
        if null_keys:
            issue("NULL_KEY", "dataset", "Row keys contain missing values.", null_keys)
        keys = duplicate_counts(
            [r for r in key_rows if not any(v in contract.null_tokens for v in r)]
        )
        keys["null_key_rows"] = null_keys
        if keys["excess_rows"]:
            severity = "error" if contract.duplicate_policy == "reject" else "warning"
            issue(
                "DUPLICATE_KEY",
                "dataset",
                "Row keys are not unique.",
                keys["excess_rows"],
                severity,
            )
    elif not contract.row_key_columns:
        issue(
            "NO_ROW_KEY",
            "dataset",
            "No row key was declared; uniqueness is not established.",
            severity="warning",
        )
    if full_duplicates["excess_rows"]:
        severity = "error" if contract.duplicate_policy == "reject" else "warning"
        issue(
            "DUPLICATE_ROWS",
            "dataset",
            "Identical source rows were detected.",
            full_duplicates["excess_rows"],
            severity,
        )
    columns = {}
    for column in df:
        values = df[column].tolist()
        valid = [v for v in values if v not in contract.null_tokens]
        columns[column] = {
            "storage_type": "string",
            "null_count": len(values) - len(valid),
            "unique_count_excluding_null": len(set(valid)),
        }
    dates = []
    if contract.date_column in df:
        invalid = missing_dates = 0
        for value in df[contract.date_column]:
            if value in contract.null_tokens:
                missing_dates += 1
                continue
            try:
                dates.append(parse_date(value, contract.date_format))
            except ValueError:
                invalid += 1
        if invalid:
            issue("DATE_PARSE_ERROR", "date", "Dates do not match the declared format.", invalid)
        if missing_dates:
            issue("NULL_DATE", "date", "Analysis dates contain missing values.", missing_dates)
        columns[contract.date_column].update({"declared_type": "date", "parse_failures": invalid})
    metrics = {}
    for metric in contract.metrics:
        scope = f"metric:{metric.id}"
        if metric.type != "additive":
            issue("UNSUPPORTED_METRIC_TYPE", scope, "Only additive metrics are supported.")
        if metric.column not in df:
            continue
        parsed = []
        invalid = null_count = 0
        for value in df[metric.column]:
            if value in contract.null_tokens:
                null_count += 1
                continue
            try:
                parsed.append(minor_units(value, metric.scale))
            except ValueError:
                invalid += 1
        if invalid:
            issue(
                "MONEY_PARSE_ERROR", scope, "Money has invalid format, precision or range.", invalid
            )
        if null_count:
            severity = "error" if metric.null_policy == "reject" else "warning"
            issue(
                "NULL_METRIC",
                scope,
                "Metric has missing values; apply its declared null policy.",
                null_count,
                severity,
            )
        negative = sum(n < 0 for n in parsed)
        if negative:
            severity = "error" if metric.negative_policy == "reject" else "warning"
            issue("NEGATIVE_VALUES", scope, "Metric contains negative values.", negative, severity)
        total = sum(parsed)
        if abs(total) > MAX_INT:
            issue("MONEY_OVERFLOW", scope, "Aggregate exceeds the fixed-point range.")
        metrics[metric.id] = {
            "valid_count": len(parsed),
            "invalid_count": invalid,
            "null_count": null_count,
            "unit": metric.unit,
            "scale": metric.scale,
            "min": money(min(parsed), metric.scale) if parsed else None,
            "max": money(max(parsed), metric.scale) if parsed else None,
            "sum": money(total, metric.scale) if abs(total) <= MAX_INT and parsed else None,
        }
        columns[metric.column].update({"declared_type": "fixed_point", "parse_failures": invalid})
    if contract.currency_column and contract.currency_column in df:
        actual = set(df[contract.currency_column])
        if any(actual != {metric.unit} for metric in contract.metrics):
            issue("CURRENCY_MISMATCH", "dataset", "Currency values do not match the metric unit.")
    if not contract.coverage_confirmed:
        issue(
            "COVERAGE_UNKNOWN",
            "coverage",
            "Date bounds do not establish complete coverage.",
            severity="warning",
        )
    elif dates and (min(dates) < contract.coverage.start or max(dates) >= contract.coverage.end):
        issue(
            "OUTSIDE_COVERAGE",
            "coverage",
            "Records lie outside the declared coverage.",
            severity="warning",
        )
    report = {
        "schema_version": "1.0",
        "dataset_id": dataset.dataset_id,
        "dataset_hash": dataset.sha256,
        "contract_fingerprint": fingerprint(contract),
        "parser": dataset.parser.model_dump(),
        "scan_scope": "full",
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": columns,
        "metrics": metrics,
        "full_row_duplicates": full_duplicates,
        "key_duplicates": keys,
        "date_bounds": {
            "min": min(dates).isoformat() if dates else None,
            "max": max(dates).isoformat() if dates else None,
        },
        "coverage_confirmed": contract.coverage_confirmed,
    }
    issues.sort(key=lambda x: (x.scope, x.code))
    return report, ValidationReport(
        analysis_readiness="blocked" if any(i.severity == "error" for i in issues) else "ready",
        issues=issues,
    )
