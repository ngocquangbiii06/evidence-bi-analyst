import csv
import hashlib
import io

import pytest
from pydantic import ValidationError

from bi_analyst.contracts import DataPolicy, ParserConfig
from bi_analyst.data import (
    MAX_INT,
    duplicate_counts,
    load_csv,
    load_csv_bytes,
    minor_units,
    profile_dataset,
)
from bi_analyst.errors import BIError


def make_csv(rows, header=None):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(
        header or ["LineID", "OrderID", "OrderDate", "CustomerID", "Region", "Product", "Revenue"]
    )
    writer.writerows(rows)
    return stream.getvalue().encode()


def test_clean_full_profile_and_leading_zeros(dataset, contract):
    profile, report = profile_dataset(dataset, contract)
    assert report.analysis_readiness == "ready"
    assert (profile["row_count"], profile["column_count"]) == (8, 7)
    assert profile["scan_scope"] == "full"
    assert dataset.frame.iloc[0]["LineID"] == "0001"
    assert profile["metrics"]["Revenue"] == {
        "valid_count": 8,
        "invalid_count": 0,
        "null_count": 0,
        "unit": "VND",
        "scale": 0,
        "min": "50",
        "max": "400",
        "sum": "1600",
    }
    assert profile["key_duplicates"] == {
        "duplicated_groups": 0,
        "involved_rows": 0,
        "excess_rows": 0,
        "null_key_rows": 0,
    }
    assert profile["columns"]["CustomerID"]["unique_count_excluding_null"] == 4


@pytest.mark.parametrize(
    "raw,code",
    [
        (b"", "EMPTY_DATASET"),
        (b"a,a\n1,2\n", "INVALID_HEADER"),
        (b"a,\n1,2\n", "INVALID_HEADER"),
        (b'a,b\n"unclosed,b', "MALFORMED_CSV"),
        (b"a,b\n1\n", "MALFORMED_CSV"),
        (b"a\n\xff", "ENCODING_ERROR"),
        (b"a\n\x00", "BINARY_CONTENT"),
    ],
)
def test_bad_csv(raw, code, policy):
    with pytest.raises(BIError) as error:
        load_csv_bytes(raw, policy)
    assert error.value.code == code


@pytest.mark.parametrize(
    "limits,raw,code",
    [
        ({"max_file_bytes": 3}, b"a\n12\n", "FILE_LIMIT"),
        ({"max_rows": 1}, b"a\n1\n2\n", "ROW_LIMIT"),
        ({"max_columns": 1}, b"a,b\n1,2\n", "COLUMN_LIMIT"),
        ({"max_cell_chars": 4}, b"a\n12345\n", "MALFORMED_CSV"),
    ],
)
def test_limits_during_read(limits, raw, code):
    with pytest.raises(BIError) as error:
        load_csv_bytes(raw, DataPolicy(**limits))
    assert error.value.code == code


def test_bom_and_delimiter(policy):
    data = load_csv_bytes(b"\xef\xbb\xbfa;b\n001;x\n", policy, ParserConfig(delimiter=";"))
    assert data.frame.iloc[0]["a"] == "001"


def test_empty_and_missing_columns(contract, policy):
    data = load_csv_bytes(b"a,b\n", policy)
    profile, report = profile_dataset(data, contract)
    assert profile["row_count"] == 0
    assert {i.code for i in report.issues} >= {"NO_DATA", "MISSING_COLUMNS"}
    assert report.analysis_readiness == "blocked"


def test_duplicates_definitions():
    assert duplicate_counts([("a",)] * 4 + [("b",)] * 2 + [("c",)]) == {
        "duplicated_groups": 2,
        "involved_rows": 6,
        "excess_rows": 4,
    }


def test_duplicate_key_does_not_imply_identical_row(contract, policy):
    data = load_csv_bytes(
        make_csv(
            [
                ["001", "O1", "2026-01-01", "C1", "N", "A", "10"],
                ["001", "O1", "2026-01-01", "C1", "N", "B", "20"],
            ]
        ),
        policy,
    )
    profile, report = profile_dataset(data, contract)
    assert profile["key_duplicates"]["duplicated_groups"] == 1
    assert profile["full_row_duplicates"]["excess_rows"] == 0
    assert report.analysis_readiness == "blocked"


@pytest.mark.parametrize(
    "value,scale,expected",
    [("0", 0, 0), ("-0.01", 2, -1), ("9007199254740993", 0, 9007199254740993), ("12.340", 2, 1234)],
)
def test_money_exact(value, scale, expected):
    assert minor_units(value, scale) == expected


@pytest.mark.parametrize("value", ["NaN", "Infinity", "1e3", "1,000", "1.2", "", str(MAX_INT + 1)])
def test_money_rejects_invalid_precision_or_range(value):
    with pytest.raises(ValueError):
        minor_units(value, 0)


def test_date_nulls_negative_currency_and_semantics(contract, policy):
    raw = make_csv([["", "O1", "03/04/2026", "C1", "N", "A", "-5"]])
    data = load_csv_bytes(raw, policy)
    changed = contract.model_copy(deep=True)
    changed.confirmed = False
    _, report = profile_dataset(data, changed)
    codes = {i.code: i.severity for i in report.issues}
    assert codes["NULL_KEY"] == "error"
    assert codes["DATE_PARSE_ERROR"] == "error"
    assert codes["SEMANTICS_UNCONFIRMED"] == "error"
    assert codes["NEGATIVE_VALUES"] == "warning"


@pytest.mark.parametrize(
    "updates",
    [
        {"grain_description": "   "},
        {"metrics": [{"id": "Sales", "column": "Revenue", "type": "additive"}]},
    ],
    ids=["blank-confirmed-grain", "missing-frozen-revenue-metric"],
)
def test_confirmed_but_unresolved_semantics_are_blocked(dataset, contract, updates):
    values = contract.model_dump(mode="json") | updates
    changed = type(contract).model_validate(values)

    _, report = profile_dataset(dataset, changed)

    assert report.analysis_readiness == "blocked"
    assert "SEMANTICS_INCOMPLETE" in {issue.code for issue in report.issues}


def test_source_is_unchanged(tmp_path, policy):
    path = tmp_path / "source.csv"
    path.write_bytes(b"a\n001\n")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    assert load_csv(path, policy).sha256 == before
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_source_symlink_rejected(tmp_path, policy):
    path = tmp_path / "source.csv"
    path.write_bytes(b"a\n001\n")
    link = tmp_path / "link.csv"
    try:
        link.symlink_to(path)
    except OSError as error:
        if getattr(error, "winerror", None) == 1314:
            pytest.skip("Windows symlink creation requires Developer Mode or elevated privilege")
        raise
    with pytest.raises(BIError):
        load_csv(link, policy)


def test_raw_samples_not_in_default_profile(contract, policy):
    raw = make_csv([["001", "O1", "2026-01-01", "canary@example.test", "N", "A", "10"]])
    profile, _ = profile_dataset(load_csv_bytes(raw, policy), contract)
    assert "canary@example.test" not in str(profile)


def test_unknown_fields_or_versions_are_rejected():
    with pytest.raises(ValidationError):
        DataPolicy(schema_version="2.0")
    with pytest.raises(ValidationError):
        DataPolicy(secret_override=True)
