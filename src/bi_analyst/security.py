"""Application-enforced egress policy; model text is never an authorization."""

from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import dataclass

from .analytics import Analytics
from .contracts import AnalysisRequest, DataPolicy, canonical, fingerprint
from .errors import BIError

FORBIDDEN_TEXT = re.compile(
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b(?:sk-|Bearer\s+|AKIA)[A-Za-z0-9_-]{8,}|-----BEGIN [A-Z ]*PRIVATE KEY-----",
    re.I,
)


@dataclass(frozen=True)
class ReviewedEvaluationProfile:
    """Exact identity for a reviewed synthetic evaluation pinned in application code."""

    question_hash: str
    request_hash: str
    dataset_hash: str
    configuration_hash: str
    endpoint: str
    stage: str
    model: str
    budget_hash: str
    initial_hypothesis_hash: str | None = None


def _budget_hash(policy: DataPolicy) -> str:
    budget = {
        key: getattr(policy, key)
        for key in [
            "max_cost_usd",
            "input_usd_per_million",
            "output_usd_per_million",
            "max_output_tokens",
            "max_model_calls",
            "max_tool_calls",
            "max_run_seconds",
            "tool_timeout_seconds",
        ]
    }
    return fingerprint(budget)


# Intentionally empty until an exact synthetic question/config/route/model/budget profile
# is reviewed and pinned for M5. There is no user or adapter configuration hook for authority.
_REVIEWED_EVALUATION_PROFILES: frozenset[ReviewedEvaluationProfile] = frozenset()


class PayloadBuilder:
    """Reconstruct outgoing views from selected fields, never serialize raw state."""

    def __init__(
        self,
        engine: Analytics,
        request: AnalysisRequest,
        policy: DataPolicy,
        *,
        m5_reviewed_profile: ReviewedEvaluationProfile | None = None,
        m5_initial_hypothesis: str | None = None,
    ):
        self.engine = engine
        self.request = request
        self.policy = policy
        self.reviewed_question_authorized = False
        self.reviewed_question_profile: ReviewedEvaluationProfile | None = None
        self.m5_reviewed_profile = m5_reviewed_profile
        self.m5_initial_hypothesis = m5_initial_hypothesis
        self.policy_hash = fingerprint(policy)
        self.labels = {}
        for dimension, column in engine.contract.dimensions.items():
            values = {
                None if v in engine.contract.null_tokens else v
                for v in engine.dataset.frame[column]
            }
            self.labels[dimension] = {
                value: f"v{index}"
                for index, value in enumerate(
                    sorted(values, key=lambda v: (v is not None, v or ""))
                )
            }

    def authorize_cloud(self):
        p = self.policy
        if p.mode != "demo_cloud" or not p.external_llm_enabled:
            raise BIError("EGRESS_DENIED", "External LLM requests are disabled by policy.")
        if "analysis" not in p.approved_stages:
            raise BIError("STAGE_DENIED", "Analysis is not approved for cloud processing.")
        if p.dataset_class not in {"synthetic", "public"}:
            raise BIError(
                "DATA_CLASS_DENIED",
                "This build only permits approved synthetic/public data for cloud use.",
            )
        if self.engine.dataset.sha256 not in p.approved_dataset_hashes:
            raise BIError(
                "DATASET_NOT_APPROVED", "Dataset hash is not approved for cloud processing."
            )
        if p.approved_endpoint != "https://api.openai.com/v1/responses":
            raise BIError("ENDPOINT_DENIED", "No approved provider endpoint.")
        if self.request.metric_id not in p.approved_metrics:
            raise BIError("METRIC_DENIED", "The metric is not approved for external processing.")
        if not set(self.request.dimensions + list(self.request.filters)).issubset(
            p.approved_dimensions
        ):
            raise BIError(
                "DIMENSION_DENIED", "A requested dimension is not approved for external processing."
            )
        if fingerprint(p) != self.policy_hash:
            raise BIError(
                "POLICY_CHANGED", "Policy changed during the run; restart with reviewed settings."
            )

    def authorize_reviewed_evaluation(self, *, endpoint: str | None, stage: str | None, model: str | None):
        """Require an exact app-controlled review profile before raw-question egress."""
        if FORBIDDEN_TEXT.search(self.request.question):
            raise BIError(
                "SENSITIVE_TEXT", "Question contains potentially sensitive content; redact it locally."
            )
        if self.policy.dataset_class != "synthetic":
            raise BIError(
                "DATA_CLASS_DENIED",
                "Reviewed question evaluation is limited to synthetic datasets.",
            )
        if not self.policy.allow_question:
            raise BIError(
                "EVALUATION_NOT_APPROVED",
                "Raw questions require an exact reviewed synthetic evaluation profile.",
            )
        if endpoint != self.policy.approved_endpoint or stage not in self.policy.approved_stages:
            raise BIError(
                "EVALUATION_NOT_APPROVED",
                "Provider endpoint or stage is not approved by the active policy.",
            )
        expected = ReviewedEvaluationProfile(
            question_hash=hashlib.sha256(self.request.question.encode("utf-8")).hexdigest(),
            request_hash=fingerprint(self.request),
            dataset_hash=self.engine.dataset.sha256,
            configuration_hash=fingerprint(
                {
                    "contract": self.engine.contract.model_dump(mode="json"),
                    "policy": self.policy.model_dump(mode="json"),
                }
            ),
            endpoint=endpoint or "",
            stage=stage or "",
            model=model or "",
            budget_hash=_budget_hash(self.policy),
            initial_hypothesis_hash=(
                hashlib.sha256(self.m5_initial_hypothesis.encode("utf-8")).hexdigest()
                if self.m5_initial_hypothesis is not None
                else None
            ),
        )
        if expected not in _REVIEWED_EVALUATION_PROFILES and expected != self.m5_reviewed_profile:
            raise BIError(
                "EVALUATION_NOT_APPROVED",
                "Question, dataset, configuration, endpoint, stage, model or budget has no exact app-pinned review.",
            )
        self.reviewed_question_authorized = True
        self.reviewed_question_profile = expected

    def encode_filters(self, filters: dict) -> dict:
        result = {}
        for dim, values in filters.items():
            if dim not in self.labels:
                raise BIError("INVALID_FILTER", "Filter dimension is not available.")
            try:
                result[dim] = [self.labels[dim][value] for value in values]
            except KeyError:
                raise BIError("INVALID_FILTER", "Filter value is not in the dataset.") from None
        return result

    def decode_filters(self, filters: list[dict]) -> dict:
        result = {}
        for item in filters:
            dim = item["dimension"]
            if dim not in self.request.dimensions and dim not in self.request.filters:
                raise BIError(
                    "FILTER_SCOPE_DENIED", "Agent cannot access an unrequested dimension."
                )
            inverse = {token: label for label, token in self.labels.get(dim, {}).items()}
            if dim in result or not item["values"] or any(v not in inverse for v in item["values"]):
                raise BIError("INVALID_FILTER", "Agent filter tokens are invalid.")
            result[dim] = [inverse[v] for v in item["values"]]
        # Agent can narrow a user filter, never widen or erase it.
        for dim, original in self.request.filters.items():
            if dim in result and not set(result[dim]).issubset(original):
                raise BIError("FILTER_SCOPE_DENIED", "Agent attempted to widen the user scope.")
            result.setdefault(dim, original)
        return result

    def result_view(self, result: dict) -> dict:
        body = {key: value for key, value in result.items() if key != "evidence_id"}
        if result.get("evidence_id") != "EV_" + fingerprint(body)[:24]:
            raise BIError("STALE_EVIDENCE", "Evidence content does not match its identifier.")
        if result["dataset_hash"] != self.engine.dataset.sha256 or result[
            "contract_fingerprint"
        ] != fingerprint(self.engine.contract):
            raise BIError(
                "STALE_EVIDENCE", "Tool evidence belongs to a different data or contract revision."
            )
        scope = result["scope"]
        if scope["metric_id"] != self.request.metric_id:
            raise BIError("METRIC_DENIED", "Evidence metric is outside the request scope.")
        dim = scope.get("dimension")
        if dim and dim not in self.request.dimensions:
            raise BIError("DIMENSION_DENIED", "Evidence dimension is outside the request scope.")
        # Explicit typed numeric fields only. Never pass arbitrary strings returned by tools.
        data = result["data"]

        def aggregate(value):
            return {
                k: value[k]
                for k in [
                    "amount",
                    "row_count",
                    "valid_count",
                    "excluded_null_count",
                    "status",
                    "coverage_confirmed",
                ]
            }

        def comparison(value):
            return {
                "previous": aggregate(value["previous"]),
                "current": aggregate(value["current"]),
                "delta": value["delta"],
                "growth_pct": value["growth_pct"],
            }

        if result["tool"] == "aggregate_metric":
            outgoing = aggregate(data)
        elif result["tool"] == "compare_periods":
            outgoing = comparison(data)
        elif result["tool"] == "breakdown_change":
            outgoing = {
                "overall": comparison(data["overall"]),
                "groups": [
                    {
                        "label": self.labels[dim][row["label"]],
                        **{
                            k: row[k]
                            for k in [
                                "previous",
                                "current",
                                "delta",
                                "net_contribution_pct",
                                "previous_rows",
                                "current_rows",
                            ]
                        },
                    }
                    for row in data["groups"]
                ],
            }
        else:
            raise BIError("TOOL_DENIED", "Evidence from an unregistered tool is not allowed.")
        safe_scope = {
            k: scope[k]
            for k in ["metric_id", "unit", "scale", "previous", "current", "period", "dimension"]
            if k in scope
        }
        safe_scope["filters"] = self.encode_filters(scope.get("filters", {}))
        return {
            "evidence_id": result["evidence_id"],
            "tool": result["tool"],
            "scope": safe_scope,
            "data": outgoing,
            "coverage_warning": "COVERAGE_UNKNOWN" in result["warnings"],
        }

    def build(
        self,
        results: list[dict],
        *,
        feedback_code: str | None = None,
        feedback_details: dict | None = None,
        predictions: list[dict] | None = None,
    ) -> dict:
        self.authorize_cloud()
        request = self.request
        question = (
            request.question
            if self.policy.allow_question
            else "Investigate the change in the selected metric between the specified periods."
        )
        if FORBIDDEN_TEXT.search(question):
            raise BIError(
                "SENSITIVE_TEXT",
                "Question contains potentially sensitive content; redact it locally.",
            )
        if self.policy.allow_question:
            profile = self.reviewed_question_profile
            if not self.reviewed_question_authorized or profile is None:
                raise BIError(
                    "EVALUATION_NOT_APPROVED",
                    "Raw questions require an exact reviewed synthetic evaluation profile.",
                )
            # Recompute at the final serialization boundary to catch request/policy mutation.
            self.authorize_reviewed_evaluation(
                endpoint=profile.endpoint, stage=profile.stage, model=profile.model
            )
        payload = {
            "task": question,
            "metric": {
                "id": request.metric_id,
                "type": "additive",
                "unit": self.engine.contract.metric(request.metric_id).unit,
            },
            "previous": request.previous.model_dump(mode="json"),
            "current": request.current.model_dump(mode="json"),
            "dimensions": [
                {"id": d, "cardinality": len(self.labels[d])} for d in request.dimensions
            ],
            "filters": self.encode_filters(request.filters),
            "observations": [self.result_view(r) for r in results],
            "feedback_code": feedback_code,
            "feedback_details": feedback_details,
        }
        if self.m5_initial_hypothesis is not None:
            if not self.reviewed_question_authorized or self.m5_reviewed_profile is None:
                raise BIError("EVALUATION_NOT_APPROVED", "Initial hypothesis has no M5 review.")
            payload["initial_hypothesis"] = self.m5_initial_hypothesis
            # E04 deliberately names a real group while evidence uses opaque labels.  The
            # reviewed synthetic bridge lets the model bind that name to the stable token
            # without sending any observed outcome or oracle value.  Keep this scoped to
            # the hypothesis' named dimension; ordinary payloads remain fully tokenized.
            hypothesis_dimensions = {
                dimension: {
                    str(label): token
                    for label, token in labels.items()
                    if label is not None
                }
                for dimension, labels in self.labels.items()
                if any(
                    label is not None
                    and isinstance(label, str)
                    and label in self.m5_initial_hypothesis
                    for label in labels
                )
            }
            if not hypothesis_dimensions:
                raise BIError(
                    "EVALUATION_SPEC_INVALID",
                    "Initial hypothesis does not identify a reviewed label dimension.",
                )
            payload["hypothesis_protocol"] = {
                "label_token_map": hypothesis_dimensions,
                "structured_prediction_events": {
                    "initial_registration": (
                        "Register the named initial hypothesis as one structured Prediction "
                        "with expected=largest_absolute_change before or while investigating "
                        "its root dimension."
                    ),
                    "revision": (
                        "After the root-dimension observation checks the prediction, if its "
                        "status is contradicted, register a new Prediction id that supersedes "
                        "the contradicted one and uses the observed label token."
                    ),
                    "runtime_enforcement": (
                        "The runtime records prediction_proposed and prediction_checked events; "
                        "do not claim a status or revise without checked evidence."
                    ),
                },
            }
        if predictions is not None:
            from .hypotheses import prediction_view

            payload["checked_predictions"] = prediction_view(predictions, self)
        serialized = canonical(payload)
        if len(serialized.encode()) > self.policy.max_payload_bytes:
            raise BIError(
                "PAYLOAD_LIMIT", "Approved context exceeds the payload limit; use a narrower scope."
            )
        if FORBIDDEN_TEXT.search(serialized):
            raise BIError(
                "SENSITIVE_TEXT", "Potentially sensitive text was blocked at the outbound boundary."
            )
        return copy.deepcopy(payload)
