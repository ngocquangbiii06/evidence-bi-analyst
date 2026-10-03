"""Exact, read-only analytics. Every result records its complete scope."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, localcontext

import pandas as pd

from .contracts import AnalysisRequest, BusinessContract, Period, fingerprint
from .data import MAX_INT, Dataset, minor_units, money, parse_date, profile_dataset
from .errors import BIError


def percent(numerator: int, denominator: int) -> str | None:
    if not denominator:
        return None
    with localcontext() as ctx:
        ctx.prec = 40
        return str(Decimal(numerator) * 100 / Decimal(denominator))


def checked_sum(values) -> int:
    total = sum(int(x) for x in values)
    if abs(total) > MAX_INT:
        raise BIError("MONEY_OVERFLOW", "Aggregate exceeds the fixed-point range.")
    return total


class Analytics:
    def __init__(self, dataset: Dataset, contract: BusinessContract):
        self.dataset = dataset
        self.contract = contract
        self.profile, self.validation = profile_dataset(dataset, contract)
        self._dates = None
        self._metrics: dict[str, pd.Series] = {}

    def _prepare(self, metric_id: str):
        metric = self.contract.metric(metric_id)
        if metric.type != "additive":
            raise BIError("UNSUPPORTED_METRIC_TYPE", "This operation requires an additive metric.")
        critical = [
            i
            for i in self.validation.issues
            if i.severity == "error"
            and (not i.scope.startswith("metric:") or i.scope == f"metric:{metric_id}")
        ]
        if critical:
            raise BIError(
                "DATA_NOT_READY",
                "Resolve critical data or semantic issues before analysis.",
                count=len(critical),
            )
        if self._dates is None:
            self._dates = self.dataset.frame[self.contract.date_column].map(
                lambda value: parse_date(value, self.contract.date_format)
            )
        if metric_id not in self._metrics:
            self._metrics[metric_id] = pd.Series(
                [
                    None if value in self.contract.null_tokens else minor_units(value, metric.scale)
                    for value in self.dataset.frame[metric.column]
                ],
                index=self.dataset.frame.index,
                dtype=object,
            )
        return metric

    def _mask(self, period: Period, filters: dict) -> pd.Series:
        mask = (self._dates >= period.start) & (self._dates < period.end)
        for dimension, values in filters.items():
            if (
                dimension not in self.contract.dimensions
                or not isinstance(values, list)
                or not values
            ):
                raise BIError("INVALID_FILTER", "Filter dimension or values are not supported.")
            column = self.contract.dimensions[dimension]
            series = self.dataset.frame[column].map(
                lambda value: None if value in self.contract.null_tokens else value
            )
            mask &= series.isin(values)
        return mask

    def _covered(self, period: Period) -> bool:
        coverage = self.contract.coverage
        return bool(
            self.contract.coverage_confirmed
            and coverage
            and coverage.start <= period.start
            and period.end <= coverage.end
        )

    def _aggregate(self, metric_id: str, period: Period, filters: dict) -> dict:
        metric = self._prepare(metric_id)
        mask = self._mask(period, filters)
        series = self._metrics[metric_id][mask]
        return self._summarize(metric, period, series)

    def _summarize(self, metric, period, series) -> dict:
        usable = [value for value in series if value is not None]
        covered = self._covered(period)
        if len(usable):
            value = checked_sum(usable)
            status = "observed"
        elif len(series):
            value = None
            status = "no_valid_values"
        else:
            value = 0 if covered else None
            status = "known_zero" if covered else "no_observations"
        return {
            "amount_minor": value,
            "amount": money(value, metric.scale),
            "row_count": len(series),
            "valid_count": len(usable),
            "excluded_null_count": len(series) - len(usable),
            "status": status,
            "coverage_confirmed": covered,
        }

    def _result(
        self, tool: str, scope: dict, data: dict, warnings: list[str] | None = None
    ) -> dict:
        body = {
            "schema_version": "1.0",
            "tool_version": "1.0",
            "tool": tool,
            "dataset_hash": self.dataset.sha256,
            "contract_fingerprint": fingerprint(self.contract),
            "scope": scope,
            "data": data,
            "warnings": sorted(set(warnings or [])),
        }
        return {**body, "evidence_id": "EV_" + fingerprint(body)[:24]}

    def aggregate_metric(self, metric_id: str, period: Period, filters: dict | None = None) -> dict:
        metric = self._prepare(metric_id)
        filters = filters or {}
        result = self._aggregate(metric_id, period, filters)
        return self._result(
            "aggregate_metric",
            {
                "metric_id": metric_id,
                "period": period.model_dump(mode="json"),
                "filters": filters,
                "unit": metric.unit,
                "scale": metric.scale,
            },
            result,
            [] if result["coverage_confirmed"] else ["COVERAGE_UNKNOWN"],
        )

    def compare_periods(self, request: AnalysisRequest) -> dict:
        metric = self._prepare(request.metric_id)
        previous = self._aggregate(metric.id, request.previous, request.filters)
        current = self._aggregate(metric.id, request.current, request.filters)
        warnings = []
        if not previous["coverage_confirmed"] or not current["coverage_confirmed"]:
            warnings.append("COVERAGE_UNKNOWN")
        if (request.current.end - request.current.start).days != (
            request.previous.end - request.previous.start
        ).days:
            warnings.append("PERIOD_LENGTHS_DIFFER")
        before, after = previous["amount_minor"], current["amount_minor"]
        delta = None if before is None or after is None else checked_sum([after, -before])
        growth = (
            percent(delta, before)
            if delta is not None and before is not None and before > 0
            else None
        )
        growth_reason = None if growth is not None else "BASELINE_NONPOSITIVE_OR_UNAVAILABLE"
        data = {
            "previous": previous,
            "current": current,
            "delta_minor": delta,
            "delta": money(delta, metric.scale),
            "growth_pct": growth,
            "growth_null_reason": growth_reason,
        }
        scope = request.model_dump(mode="json", exclude={"question", "dimensions"}) | {
            "unit": metric.unit,
            "scale": metric.scale,
        }
        return self._result("compare_periods", scope, data, warnings)

    def breakdown_change(self, request: AnalysisRequest, dimension: str) -> dict:
        if dimension not in self.contract.dimensions:
            raise BIError("UNKNOWN_DIMENSION", "Dimension is not registered in the contract.")
        metric = self._prepare(request.metric_id)
        overall = self.compare_periods(request)
        column = self.contract.dimensions[dimension]
        groups = []
        for period in [request.previous, request.current]:
            mask = self._mask(period, request.filters)
            grouped = defaultdict(list)
            for label, value in zip(
                self.dataset.frame.loc[mask, column], self._metrics[metric.id][mask]
            ):
                grouped[None if label in self.contract.null_tokens else label].append(value)
            groups.append(grouped)
        labels = set(groups[0]) | set(groups[1])
        if len(labels) > 1000:
            raise BIError(
                "HIGH_CARDINALITY", "Breakdown exceeds 1,000 groups; use a coarser dimension."
            )
        rows = []
        for label in sorted(labels, key=lambda value: (value is not None, value or "")):
            previous = self._summarize(metric, request.previous, groups[0].get(label, []))
            current = self._summarize(metric, request.current, groups[1].get(label, []))
            before, after = previous["amount_minor"], current["amount_minor"]
            delta = None if before is None or after is None else checked_sum([after, -before])
            net = overall["data"]["delta_minor"]
            rows.append(
                {
                    "label": label,
                    "previous_minor": before,
                    "current_minor": after,
                    "delta_minor": delta,
                    "previous": previous["amount"],
                    "current": current["amount"],
                    "delta": money(delta, metric.scale),
                    "net_contribution_pct": percent(delta, net)
                    if delta is not None and net is not None
                    else None,
                    "previous_rows": previous["row_count"],
                    "current_rows": current["row_count"],
                    "previous_valid_count": previous["valid_count"],
                    "current_valid_count": current["valid_count"],
                    "previous_excluded_null_count": previous["excluded_null_count"],
                    "current_excluded_null_count": current["excluded_null_count"],
                    "previous_status": previous["status"],
                    "current_status": current["status"],
                    "previous_coverage_confirmed": previous["coverage_confirmed"],
                    "current_coverage_confirmed": current["coverage_confirmed"],
                }
            )
        rows.sort(
            key=lambda row: (
                row["delta_minor"] is None,
                row["delta_minor"] or 0,
                row["label"] or "",
            )
        )
        deltas = [row["delta_minor"] for row in rows]
        can_reconcile = (
            all(value is not None for value in deltas)
            and overall["data"]["delta_minor"] is not None
        )
        reconciled = (
            checked_sum(deltas) == overall["data"]["delta_minor"] if can_reconcile else None
        )
        if reconciled is False:
            raise BIError(
                "RECONCILIATION_FAILED", "Group deltas do not reconcile to the overall scope."
            )
        return self._result(
            "breakdown_change",
            overall["scope"] | {"dimension": dimension},
            {
                "overall": overall["data"],
                "groups": rows,
                "numerical_validation": "passed" if reconciled else "not_checked",
                "net_contribution_definition": "100 * segment_delta / overall_delta",
                "contribution_null_reason": "OVERALL_DELTA_ZERO_OR_UNAVAILABLE"
                if not overall["data"]["delta_minor"]
                else None,
            },
            overall["warnings"],
        )
