"""Check bounded, observational predictions against computed evidence."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .contracts import Schema
from .errors import BIError


class Prediction(Schema):
    prediction_id: str = Field(pattern=r"^H[1-9][0-9]{0,2}$")
    dimension: str = Field(max_length=64)
    label_token: str = Field(pattern=r"^v[0-9]+$")
    expected: Literal["decline", "increase", "largest_absolute_change"]
    supersedes: str | None = Field(default=None, pattern=r"^H[1-9][0-9]{0,2}$")


def register_predictions(ledger: list[dict], predictions: list[Prediction], builder, filters: dict):
    known = {item["prediction_id"]: item for item in ledger}
    staged = []
    for prediction in predictions:
        if prediction.dimension not in builder.request.dimensions:
            raise BIError(
                "DIMENSION_DENIED", "Prediction dimension is outside the requested scope."
            )
        labels = builder.labels[prediction.dimension]
        if prediction.label_token not in labels.values():
            raise BIError("INVALID_PREDICTION", "Prediction refers to an unknown label token.")
        if prediction.prediction_id in known:
            old = known[prediction.prediction_id]
            if (
                any(old[k] != v for k, v in prediction.model_dump().items())
                or old["filters"] != filters
            ):
                raise BIError("INVALID_PREDICTION", "A revised prediction needs a new identifier.")
            continue
        if prediction.supersedes and prediction.supersedes not in known:
            raise BIError("INVALID_PREDICTION", "A revision must refer to an existing prediction.")
        if len(ledger) + len(staged) >= 10:
            raise BIError("PREDICTION_LIMIT", "Prediction budget exhausted.")
        item = prediction.model_dump() | {
            "filters": filters.copy(),
            "status": "proposed",
            "evidence_ids": [],
            "validation": "not_checked",
        }
        staged.append(item)
        known[prediction.prediction_id] = item
    ledger.extend(staged)


def evaluate_predictions(ledger: list[dict], result: dict, builder) -> list[dict]:
    if result["tool"] != "breakdown_change":
        return []
    scope, data = result["scope"], result["data"]
    changes = []
    for item in ledger:
        if item["dimension"] != scope["dimension"] or item["filters"] != scope["filters"]:
            continue
        if result["evidence_id"] in item["evidence_ids"]:
            continue
        token_map = builder.labels[item["dimension"]]
        rows = data["groups"]
        row = next((r for r in rows if token_map[r["label"]] == item["label_token"]), None)
        supported = None
        if row is not None and row["delta_minor"] is not None:
            if item["expected"] == "decline":
                supported = row["delta_minor"] < 0
            elif item["expected"] == "increase":
                supported = row["delta_minor"] > 0
            elif all(r["delta_minor"] is not None for r in rows):
                supported = abs(row["delta_minor"]) == max(abs(r["delta_minor"]) for r in rows)
        item["status"] = (
            "inconclusive"
            if supported is None
            else ("supported_by_observation" if supported else "contradicted")
        )
        item["validation"] = "registered_observational_predicate"
        item["evidence_ids"].append(result["evidence_id"])
        changes.append(
            {
                "event": "prediction_checked",
                "prediction_id": item["prediction_id"],
                "status": item["status"],
                "evidence_id": result["evidence_id"],
            }
        )
    return changes


def prediction_view(ledger: list[dict], builder) -> list[dict]:
    return [
        {
            key: item[key]
            for key in [
                "prediction_id",
                "dimension",
                "label_token",
                "expected",
                "supersedes",
                "status",
                "evidence_ids",
            ]
        }
        | {"filters": builder.encode_filters(item["filters"])}
        for item in ledger
    ]
