from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_data import make_csv

from bi_analyst.analytics import Analytics
from bi_analyst.contracts import AnalysisRequest
from bi_analyst.data import load_csv_bytes
from bi_analyst.errors import BIError


def test_known_answers(dataset, contract, request_spec):
    engine = Analytics(dataset, contract)
    result = engine.compare_periods(request_spec)
    assert result["data"]["previous"]["amount"] == "1000"
    assert result["data"]["current"]["amount"] == "600"
    assert result["data"]["delta"] == "-400"
    assert result["data"]["previous"]["status"] == "observed"
    assert result["data"]["previous"]["coverage_confirmed"] is True
    assert result["data"]["previous"]["row_count"] == 4
    assert result["data"]["previous"]["valid_count"] == 4
    assert result["data"]["previous"]["excluded_null_count"] == 0
    assert Decimal(result["data"]["growth_pct"]) == -40
    breakdown = engine.breakdown_change(request_spec, "Region")
    groups = {row["label"]: row for row in breakdown["data"]["groups"]}
    assert groups["South"]["delta"] == "-250"
    assert Decimal(groups["South"]["net_contribution_pct"]) == Decimal("62.5")
    assert groups["North"]["delta"] == "-150"
    assert breakdown["data"]["numerical_validation"] == "passed"


def test_filters_evidence_and_conditional_denominator(dataset, contract, request_spec):
    engine = Analytics(dataset, contract)
    all_result = engine.breakdown_change(request_spec, "Product")
    child = request_spec.model_copy(deep=True)
    child.filters = {"Region": ["South"]}
    south = engine.breakdown_change(child, "Product")
    assert south["scope"]["filters"] == {"Region": ["South"]}
    assert south["data"]["overall"]["delta"] == "-250"
    assert all_result["evidence_id"] != south["evidence_id"]
    assert engine.breakdown_change(child, "Product") == south


@pytest.mark.parametrize(
    "before,after,delta,percent", [(0, 10, 10, None), (-10, 10, 20, None), (10, 0, -10, "-100")]
)
def test_zero_and_negative_baseline(contract, policy, request_spec, before, after, delta, percent):
    data = load_csv_bytes(
        make_csv(
            [
                ["1", "O1", "2026-01-05", "C1", "N", "A", str(before)],
                ["2", "O2", "2026-02-05", "C1", "N", "A", str(after)],
            ]
        ),
        policy,
    )
    result = Analytics(data, contract).compare_periods(request_spec)["data"]
    assert result["delta_minor"] == delta
    assert result["growth_pct"] == percent


def test_contribution_over_100_and_zero_net(contract, policy, request_spec):
    rows = [
        ["1", "O1", "2026-01-05", "C1", "South", "A", "200"],
        ["2", "O2", "2026-01-05", "C2", "North", "A", "100"],
        ["3", "O3", "2026-02-05", "C1", "South", "A", "80"],
        ["4", "O4", "2026-02-05", "C2", "North", "A", "120"],
    ]
    result = Analytics(load_csv_bytes(make_csv(rows), policy), contract).breakdown_change(
        request_spec, "Region"
    )["data"]
    values = {r["label"]: Decimal(r["net_contribution_pct"]) for r in result["groups"]}
    assert values == {"South": Decimal(120), "North": Decimal(-20)}
    rows[-1][-1] = "220"
    result = Analytics(load_csv_bytes(make_csv(rows), policy), contract).breakdown_change(
        request_spec, "Region"
    )["data"]
    assert result["overall"]["delta_minor"] == 0
    assert all(r["net_contribution_pct"] is None for r in result["groups"])


def test_missing_period_not_zero_without_coverage(dataset, contract, request_spec):
    changed = contract.model_copy(deep=True)
    changed.coverage_confirmed = False
    altered = AnalysisRequest.model_validate(
        request_spec.model_dump(mode="json")
        | {"current": {"start": "2026-03-01", "end": "2026-04-01"}}
    )
    result = Analytics(dataset, changed).compare_periods(altered)
    assert result["data"]["current"]["amount"] is None
    assert result["data"]["current"]["status"] == "no_observations"
    assert result["data"]["current"]["row_count"] == 0
    assert result["data"]["current"]["coverage_confirmed"] is False
    assert result["data"]["delta"] is None
    assert "COVERAGE_UNKNOWN" in result["warnings"]


def test_outer_groups_and_null_dimension(contract, policy, request_spec):
    rows = [
        ["1", "O1", "2026-01-05", "C1", "", "A", "10"],
        ["2", "O2", "2026-02-05", "C2", "South", "B", "20"],
    ]
    result = Analytics(load_csv_bytes(make_csv(rows), policy), contract).breakdown_change(
        request_spec, "Region"
    )["data"]
    groups = {r["label"]: r for r in result["groups"]}
    assert groups[None]["current"] == "0"
    assert groups["South"]["previous"] == "0"
    assert result["numerical_validation"] == "passed"


def test_null_exclusion_does_not_round_large_integers(contract, policy, request_spec):
    changed = contract.model_copy(deep=True)
    changed.metrics[0].null_policy = "exclude"
    rows = [
        ["1", "O1", "2026-01-05", "C1", "N", "A", "9007199254740993"],
        ["2", "O2", "2026-01-05", "C2", "N", "A", ""],
        ["3", "O3", "2026-02-05", "C1", "N", "A", "9007199254740992"],
    ]
    result = Analytics(load_csv_bytes(make_csv(rows), policy), changed).compare_periods(
        request_spec
    )["data"]
    assert result["delta_minor"] == -1
    assert result["previous"]["status"] == "observed"
    assert result["previous"]["row_count"] == 2
    assert result["previous"]["valid_count"] == 1
    assert result["previous"]["excluded_null_count"] == 1


def test_all_null_period_is_unavailable_not_zero(contract, policy, request_spec):
    changed = contract.model_copy(deep=True)
    changed.metrics[0].null_policy = "exclude"
    rows = [
        ["1", "O1", "2026-01-05", "C1", "South", "A", "100"],
        ["2", "O2", "2026-02-05", "C2", "North", "A", ""],
    ]
    result = Analytics(load_csv_bytes(make_csv(rows), policy), changed).compare_periods(
        request_spec
    )
    current = result["data"]["current"]
    assert current["status"] == "no_valid_values"
    assert current["row_count"] == 1
    assert current["valid_count"] == 0
    assert current["excluded_null_count"] == 1
    assert current["coverage_confirmed"] is True
    assert current["amount_minor"] is current["amount"] is None
    assert result["data"]["delta_minor"] is result["data"]["delta"] is None


def test_metric_and_filter_rejection(dataset, contract, request_spec):
    engine = Analytics(dataset, contract)
    with pytest.raises(BIError):
        engine.breakdown_change(request_spec, "read_file")
    bad = request_spec.model_copy(deep=True)
    bad.filters = {"CustomerID": ["C001"]}
    with pytest.raises(BIError):
        engine.compare_periods(bad)
    unsupported = contract.model_copy(deep=True)
    unsupported.metrics[0].type = "ratio"
    with pytest.raises(BIError) as error:
        Analytics(dataset, unsupported).compare_periods(request_spec)
    assert error.value.code == "UNSUPPORTED_METRIC_TYPE"


def test_overlapping_periods_rejected(request_spec):
    values = request_spec.model_dump(mode="json")
    values["current"] = values["previous"]
    with pytest.raises(ValidationError):
        AnalysisRequest.model_validate(values)
