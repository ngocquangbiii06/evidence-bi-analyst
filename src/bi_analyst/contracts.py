"""Versioned contracts. Untrusted model arguments use the same strict boundary."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, allow_inf_nan=False)


class Versioned(Schema):
    schema_version: Literal["1.0"] = "1.0"


class Period(Schema):
    start: date
    end: date  # exclusive

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end <= self.start:
            raise ValueError("Period end must be after start (exclusive).")
        return self


class Metric(Schema):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
    column: str = Field(min_length=1, max_length=128)
    type: Literal["additive", "ratio", "distinct_count", "snapshot"] = "additive"
    aggregation: Literal["sum"] = "sum"
    unit: str = Field(default="VND", pattern=r"^[A-Z]{3}$")
    scale: int = Field(default=0, ge=0, le=4)
    null_policy: Literal["reject", "exclude"] = "reject"
    negative_policy: Literal["allow", "reject"] = "allow"
    grain: Literal["row"] = "row"


class BusinessContract(Versioned):
    contract_id: str = Field(default="sales", pattern=r"^[A-Za-z0-9_-]{1,64}$")
    revision: int = Field(default=1, ge=1)
    confirmed: bool = False
    grain_description: str = Field(min_length=1, max_length=300)
    row_key_columns: list[str] = Field(default_factory=list, max_length=8)
    duplicate_policy: Literal["reject", "allow_confirmed"] = "reject"
    date_column: str = Field(min_length=1, max_length=128)
    date_format: Literal["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"] = "%Y-%m-%d"
    metrics: list[Metric] = Field(min_length=1, max_length=20)
    dimensions: dict[str, str] = Field(default_factory=dict, max_length=20)
    currency_column: str | None = None
    coverage: Period | None = None
    coverage_confirmed: bool = False
    null_tokens: list[str] = Field(default_factory=lambda: [""], max_length=20)

    @model_validator(mode="after")
    def valid_catalog(self) -> Self:
        ids = [m.id for m in self.metrics]
        if len(set(ids)) != len(ids):
            raise ValueError("Metric IDs must be unique.")
        for key in self.dimensions:
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", key):
                raise ValueError("Dimension ID must be a safe identifier.")
        if len(set(self.row_key_columns)) != len(self.row_key_columns):
            raise ValueError("Repeated key columns.")
        if self.coverage_confirmed and self.coverage is None:
            raise ValueError("Confirmed coverage requires a range.")
        return self

    def metric(self, metric_id: str) -> Metric:
        from .errors import BIError

        for metric in self.metrics:
            if metric.id == metric_id:
                return metric
        raise BIError("UNKNOWN_METRIC", "Metric is not registered in the business contract.")


class ParserConfig(Schema):
    encoding: Literal["utf-8-sig", "utf-8"] = "utf-8-sig"
    delimiter: Literal[",", ";", "\t"] = ","


class DataPolicy(Versioned):
    policy_id: str = Field(default="local-default", pattern=r"^[A-Za-z0-9_-]{1,64}$")
    revision: int = Field(default=1, ge=1)
    mode: Literal["local_only", "demo_cloud", "restricted_cloud"] = "local_only"
    external_llm_enabled: bool = False
    dataset_class: Literal["unknown", "synthetic", "public", "confidential"] = "unknown"
    approved_dataset_hashes: list[str] = Field(default_factory=list)
    approved_endpoint: Literal["https://api.openai.com/v1/responses"] | None = None
    approved_metrics: list[str] = Field(default_factory=list)
    approved_dimensions: list[str] = Field(default_factory=list)
    allow_question: bool = False
    approved_stages: list[Literal["analysis", "semantic_review", "bi_planning"]] = Field(
        default_factory=lambda: ["analysis"], max_length=3
    )
    approved_schema_columns: list[str] = Field(default_factory=list, max_length=100)
    max_file_bytes: int = Field(default=50 * 1024 * 1024, ge=1, le=50 * 1024 * 1024)
    max_rows: int = Field(default=200_000, ge=1, le=200_000)
    max_columns: int = Field(default=100, ge=1, le=100)
    max_cell_chars: int = Field(default=4096, ge=1, le=4096)
    max_payload_bytes: int = Field(default=32_768, ge=512, le=65_536)
    max_tool_calls: int = Field(default=12, ge=1, le=30)
    max_run_seconds: int = Field(default=180, ge=1, le=600)
    tool_timeout_seconds: int = Field(default=15, ge=1, le=60)
    max_model_calls: int = Field(default=16, ge=1, le=40)
    max_output_tokens: int = Field(default=1200, ge=64, le=4096)
    max_cost_usd: float = Field(default=0, ge=0, le=100)
    input_usd_per_million: float = Field(default=0, ge=0)
    output_usd_per_million: float = Field(default=0, ge=0)
    ttl_hours: int = Field(default=24, ge=1, le=168)

    @field_validator("approved_dataset_hashes")
    @classmethod
    def hashes(cls, values: list[str]) -> list[str]:
        if any(not re.fullmatch(r"[a-f0-9]{64}", value) for value in values):
            raise ValueError("Expected SHA256 dataset hashes.")
        return values


class AnalysisRequest(Schema):
    question: str = Field(default="What changed between the two periods?", max_length=2000)
    metric_id: str
    previous: Period
    current: Period
    dimensions: list[str] = Field(default_factory=list, max_length=20)
    filters: dict[str, list[str | None]] = Field(default_factory=dict, max_length=20)

    @model_validator(mode="after")
    def nonoverlapping(self) -> Self:
        if max(self.previous.start, self.current.start) < min(self.previous.end, self.current.end):
            raise ValueError("Comparison periods must not overlap.")
        return self


ValidationState = Literal["passed", "failed", "not_checked", "not_applicable"]


class AnalysisScope(Schema):
    """Canonical comparison scope used at the finding-validation boundary."""

    metric_id: str
    previous: Period
    current: Period
    filters: dict[str, list[str | None]] = Field(default_factory=dict, max_length=20)
    unit: str
    scale: int = Field(ge=0, le=4)
    dimension: str | None = None


class TrustedEvidenceCall(Schema):
    """Expected tool output context recorded by the trusted executor caller."""

    tool: Literal["aggregate_metric", "compare_periods", "breakdown_change"]
    scope: AnalysisScope
    aggregate_period: Literal["previous", "current"] | None = None

    @model_validator(mode="after")
    def aggregate_period_matches_tool(self) -> Self:
        if (self.tool == "aggregate_metric") != (self.aggregate_period is not None):
            raise ValueError("Aggregate evidence requires its exact requested period.")
        return self


class TrustedAnalysisContext(Schema):
    """Caller-provided execution context used to validate evidence provenance and scope."""

    dataset_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    contract_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    root_scope: AnalysisScope
    coverage: Period | None = None
    coverage_confirmed: bool = False
    null_policy: Literal["reject", "exclude"] = "reject"
    allowed_dimensions: list[str] = Field(default_factory=list, max_length=20)
    allowed_filter_dimensions: list[str] = Field(default_factory=list, max_length=20)
    evidence_calls: dict[str, TrustedEvidenceCall] = Field(default_factory=dict)

    @model_validator(mode="after")
    def confirmed_coverage_has_range(self) -> Self:
        if self.coverage_confirmed and self.coverage is None:
            raise ValueError("Trusted confirmed coverage requires a range.")
        return self


class TrustedAnalysisLoadContext(Schema):
    """Current caller-trusted dependencies required to load one analysis artifact."""

    dataset_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed_contract_snapshot: BusinessContract
    root_request: AnalysisRequest
    implementation_version: str = Field(min_length=1, max_length=64)
    validator_version: str = Field(min_length=1, max_length=64)
    finding_context: TrustedAnalysisContext

    @model_validator(mode="after")
    def dependencies_are_consistent(self) -> Self:
        contract = self.confirmed_contract_snapshot
        if not contract.confirmed:
            raise ValueError("Trusted load context requires a confirmed business contract.")
        if any(dimension not in contract.dimensions for dimension in self.root_request.dimensions):
            raise ValueError("Trusted root request contains an unregistered dimension.")
        if any(dimension not in contract.dimensions for dimension in self.root_request.filters):
            raise ValueError("Trusted root request contains an unregistered filter dimension.")

        metric = next(
            (item for item in contract.metrics if item.id == self.root_request.metric_id), None
        )
        if metric is None:
            raise ValueError("Trusted root request metric is not registered in the contract.")
        expected_scope = AnalysisScope(
            metric_id=self.root_request.metric_id,
            previous=self.root_request.previous,
            current=self.root_request.current,
            filters=self.root_request.filters,
            unit=metric.unit,
            scale=metric.scale,
        )
        finding_context = self.finding_context
        if finding_context.dataset_hash != self.dataset_hash:
            raise ValueError("Trusted finding context dataset hash does not match load context.")
        if finding_context.contract_fingerprint != fingerprint(contract):
            raise ValueError("Trusted finding context contract does not match load context.")
        if canonical(finding_context.root_scope) != canonical(expected_scope):
            raise ValueError("Trusted finding context root scope does not match load context.")
        if (
            finding_context.coverage != contract.coverage
            or finding_context.coverage_confirmed != contract.coverage_confirmed
            or finding_context.null_policy != metric.null_policy
        ):
            raise ValueError("Trusted finding context semantics do not match load context.")
        if finding_context.allowed_dimensions != self.root_request.dimensions:
            raise ValueError("Trusted finding context dimensions do not match root request.")
        expected_filter_dimensions = list(
            dict.fromkeys(self.root_request.dimensions + list(self.root_request.filters))
        )
        if finding_context.allowed_filter_dimensions != expected_filter_dimensions:
            raise ValueError("Trusted finding context filters do not match root request.")
        return self


class CandidateFinding(Schema):
    """A typed claim proposal. It deliberately carries no validation status."""

    finding_id: str = Field(pattern=r"^F[0-9]{3,}$")
    claim_type: Literal["observation", "contribution"]
    evidence_id: str
    scope: AnalysisScope
    text: str
    field_refs: list[str] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)
    previous_minor: int | None = None
    current_minor: int | None = None
    delta_minor: int
    previous: str | None = None
    current: str | None = None
    delta: str
    group_index: int | None = Field(default=None, ge=0)
    label: str | None = None
    net_contribution_pct: str | None = None


class FindingValidation(Schema):
    """Independent M1.1 checks; unchecked is never promoted to passed."""

    numerical: ValidationState = "not_checked"
    evidence_linkage: ValidationState = "not_checked"
    scope: ValidationState = "not_checked"
    interpretation: ValidationState = "not_checked"
    accepted: bool = False
    reasons: list[str] = Field(default_factory=list)


SufficiencyStatus = Literal["completed", "partial", "abstained", "needs_input"]
AnalysisMode = Literal["deterministic", "test_adapter", "live_agent"]
GoalDisposition = Literal["supported_descriptive", "unsupported_causal", "unresolved"]


class ArtifactFinding(Schema):
    """A candidate paired with the independent validator's verdict."""

    candidate: CandidateFinding
    validation: FindingValidation

    @model_validator(mode="after")
    def verdict_matches_checks(self) -> Self:
        states = (
            self.validation.evidence_linkage,
            self.validation.scope,
            self.validation.numerical,
            self.validation.interpretation,
        )
        if self.validation.accepted != all(state == "passed" for state in states):
            raise ValueError("Finding acceptance must match the validator check states.")
        return self


class AnalysisTraceEvent(Schema):
    """Minimal investigation trace; it stores actions and references, not reasoning text."""

    revision: int = Field(ge=1)
    kind: Literal["tool_call", "prediction", "revision", "rejection", "ask", "finish"]
    tool: Literal["aggregate_metric", "compare_periods", "breakdown_change"] | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)


class AnalysisObligations(Schema):
    """Root-request obligations and the evidence that fulfilled each one."""

    required: list[str]
    fulfilled: list[str]
    missing: list[str]
    evidence_by_obligation: dict[str, list[str]]


class AnalysisExecutionError(Schema):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    stage: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=1000)


class AnalysisUsage(Schema):
    """Unknown usage remains null; it is never silently treated as zero."""

    tool_calls: int | None = Field(default=None, ge=0)
    model_calls: int | None = Field(default=None, ge=0)
    elapsed_seconds: float | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)


def required_obligation_ids(
    request: AnalysisRequest, goal_disposition: GoalDisposition
) -> list[str]:
    """Derive the complete obligation set from the frozen root request/disposition."""

    obligations = [
        "overall.previous_total",
        "overall.current_total",
        "overall.delta",
        *(f"dimension.{dimension}.breakdown" for dimension in request.dimensions),
    ]
    if goal_disposition == "unsupported_causal":
        obligations.append("goal.causal_explanation")
    elif goal_disposition == "unresolved":
        obligations.append("goal.semantic_clarification")
    return obligations


# Normative policy for future consumers. T06 defines this boundary without
# implementing a loader: old artifacts are never upgraded, stale ones are never
# recomputed in place, and missing artifacts are never synthesized by a reader.
ARTIFACT_LOAD_POLICY = {
    "legacy": "reject_require_new_run",
    "stale": "reject_require_new_run",
    "missing": "report_missing_without_synthesis",
}


ARTIFACT_FINGERPRINT_FIELDS = (
    "artifact_version",
    "schema_version",
    "validator_version",
    "implementation_version",
    "dataset_hash",
    "confirmed_contract_snapshot",
    "contract_fingerprint",
    "root_request",
    "root_request_fingerprint",
    "root_scope",
    "mode",
    "goal_disposition",
    "trace_revision",
    "investigation_trace",
    "prediction_revisions",
    "evidence_registry",
    "root_evidence_ids",
    "findings",
    "accepted_finding_ids",
    "rejected_finding_ids",
    "obligations",
    "sufficiency_status",
    "limitations",
    "clarification_request",
    "execution_status",
    "errors",
    "usage",
)


class ValidatedAnalysisArtifact(Versioned):
    """Authoritative, self-identifying analysis result envelope for one run."""

    # Require explicit versions so a legacy payload cannot inherit defaults and
    # appear current merely by being parsed with this schema.
    schema_version: Literal["1.0"] = Field(...)
    artifact_version: Literal["1.0"] = Field(...)
    validator_version: str = Field(min_length=1, max_length=64)
    implementation_version: str = Field(min_length=1, max_length=64)
    dataset_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed_contract_snapshot: BusinessContract
    contract_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    root_request: AnalysisRequest
    root_request_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    root_scope: AnalysisScope
    mode: AnalysisMode
    goal_disposition: GoalDisposition
    trace_revision: int = Field(ge=0)
    investigation_trace: list[AnalysisTraceEvent]
    prediction_revisions: list[int]
    evidence_registry: dict[str, dict[str, Any]]
    root_evidence_ids: list[str]
    findings: list[ArtifactFinding]
    accepted_finding_ids: list[str]
    rejected_finding_ids: list[str]
    obligations: AnalysisObligations
    sufficiency_status: SufficiencyStatus | None
    limitations: list[str]
    clarification_request: str | None = Field(..., max_length=2000)
    execution_status: Literal["succeeded", "failed", "cancelled", "expired"]
    errors: list[AnalysisExecutionError]
    usage: AnalysisUsage
    content_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def internally_consistent(self) -> Self:
        if not self.confirmed_contract_snapshot.confirmed:
            raise ValueError("Artifact requires a confirmed business contract snapshot.")
        if fingerprint(self.confirmed_contract_snapshot) != self.contract_fingerprint:
            raise ValueError("Contract snapshot fingerprint mismatch.")
        if fingerprint(self.root_request) != self.root_request_fingerprint:
            raise ValueError("Root request fingerprint mismatch.")

        request = self.root_request
        scope = self.root_scope
        if (
            scope.metric_id != request.metric_id
            or scope.previous != request.previous
            or scope.current != request.current
            or canonical(scope.filters) != canonical(request.filters)
            or scope.dimension is not None
        ):
            raise ValueError("Root scope must exactly match the approved root request.")
        if len(set(request.dimensions)) != len(request.dimensions):
            raise ValueError("Root request dimensions must be unique.")
        if any(dimension not in self.confirmed_contract_snapshot.dimensions for dimension in request.dimensions):
            raise ValueError("Root request contains a dimension outside the confirmed contract.")
        if any(dimension not in self.confirmed_contract_snapshot.dimensions for dimension in request.filters):
            raise ValueError("Root request contains a filter outside the confirmed contract.")
        metric = next(
            (item for item in self.confirmed_contract_snapshot.metrics if item.id == request.metric_id),
            None,
        )
        if metric is None:
            raise ValueError("Root request metric is outside the confirmed contract.")
        if scope.unit != metric.unit or scope.scale != metric.scale:
            raise ValueError("Root scope unit and scale must match the confirmed metric.")

        evidence_ids = list(self.evidence_registry)
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("Evidence registry IDs must be unique.")
        for evidence_id, record in self.evidence_registry.items():
            if record.get("evidence_id") != evidence_id:
                raise ValueError("Evidence registry key must match the evidence record ID.")

        if len(set(self.root_evidence_ids)) != len(self.root_evidence_ids):
            raise ValueError("Root evidence IDs must be unique.")
        if any(evidence_id not in self.evidence_registry for evidence_id in self.root_evidence_ids):
            raise ValueError("Root evidence IDs must resolve to registered evidence.")
        root_evidence = {}
        for evidence_id in self.root_evidence_ids:
            record = self.evidence_registry[evidence_id]
            try:
                evidence_scope = AnalysisScope.model_validate(record.get("scope", {}))
            except (TypeError, ValueError):
                raise ValueError("Root evidence scope is invalid.") from None
            is_root_scope = (
                evidence_scope.metric_id == scope.metric_id
                and evidence_scope.previous == scope.previous
                and evidence_scope.current == scope.current
                and canonical(evidence_scope.filters) == canonical(scope.filters)
                and evidence_scope.unit == scope.unit
                and evidence_scope.scale == scope.scale
            )
            tool = record.get("tool")
            dimension = evidence_scope.dimension
            if is_root_scope and tool == "compare_periods" and dimension is None:
                root_evidence[evidence_id] = (tool, dimension)
            elif is_root_scope and tool == "breakdown_change" and dimension in request.dimensions:
                root_evidence[evidence_id] = (tool, dimension)
            else:
                raise ValueError("Root evidence must use the exact root scope and a requested tool.")

        finding_ids = [record.candidate.finding_id for record in self.findings]
        if len(set(finding_ids)) != len(finding_ids):
            raise ValueError("Candidate finding IDs must be unique.")
        for record in self.findings:
            if record.candidate.evidence_id not in self.evidence_registry:
                raise ValueError("Candidate finding references missing evidence.")
        expected_accepted = [
            record.candidate.finding_id for record in self.findings if record.validation.accepted
        ]
        expected_rejected = [
            record.candidate.finding_id for record in self.findings if not record.validation.accepted
        ]
        if len(set(self.accepted_finding_ids)) != len(self.accepted_finding_ids):
            raise ValueError("Accepted finding IDs must be unique.")
        if len(set(self.rejected_finding_ids)) != len(self.rejected_finding_ids):
            raise ValueError("Rejected finding IDs must be unique.")
        if self.accepted_finding_ids != expected_accepted:
            raise ValueError("Accepted IDs must be derived from the finding validation verdicts.")
        if self.rejected_finding_ids != expected_rejected:
            raise ValueError("Rejected IDs must be derived from the finding validation verdicts.")
        if set(self.accepted_finding_ids) & set(self.rejected_finding_ids):
            raise ValueError("A finding cannot be both accepted and rejected.")

        trace_revisions = [event.revision for event in self.investigation_trace]
        if trace_revisions != sorted(set(trace_revisions)):
            raise ValueError("Investigation trace revisions must be unique and increasing.")
        if self.trace_revision != (trace_revisions[-1] if trace_revisions else 0):
            raise ValueError("Trace revision must identify the latest recorded trace event.")
        prediction_revisions = self.prediction_revisions
        if len(set(prediction_revisions)) != len(prediction_revisions):
            raise ValueError("Prediction revisions must be unique.")
        prediction_event_revisions = {
            event.revision for event in self.investigation_trace if event.kind == "prediction"
        }
        if any(revision not in prediction_event_revisions for revision in prediction_revisions):
            raise ValueError("Prediction revisions must resolve to prediction trace events.")
        finding_id_set = set(finding_ids)
        for event in self.investigation_trace:
            if any(evidence_id not in self.evidence_registry for evidence_id in event.evidence_ids):
                raise ValueError("Trace event references missing evidence.")
            if any(finding_id not in finding_id_set for finding_id in event.finding_ids):
                raise ValueError("Trace event references a missing candidate finding.")

        required = required_obligation_ids(request, self.goal_disposition)
        if self.obligations.required != required:
            raise ValueError("Required obligations must be derived from the approved root request.")
        fulfilled = self.obligations.fulfilled
        missing = self.obligations.missing
        if len(set(required)) != len(required):
            raise ValueError("Required obligation IDs must be unique.")
        if len(set(fulfilled)) != len(fulfilled) or len(set(missing)) != len(missing):
            raise ValueError("Fulfilled and missing obligation IDs must be unique.")
        if set(fulfilled) & set(missing) or set(fulfilled) | set(missing) != set(required):
            raise ValueError("Fulfilled and missing obligations must partition required obligations.")
        if fulfilled != [item for item in required if item in set(fulfilled)]:
            raise ValueError("Fulfilled obligations must retain required-obligation order.")
        if missing != [item for item in required if item in set(missing)]:
            raise ValueError("Missing obligations must retain required-obligation order.")
        if set(self.obligations.evidence_by_obligation) != set(fulfilled):
            raise ValueError("Each fulfilled obligation must have evidence, and only fulfilled obligations may.")
        for evidence_refs in self.obligations.evidence_by_obligation.values():
            if not evidence_refs or len(set(evidence_refs)) != len(evidence_refs):
                raise ValueError("Fulfilled obligations require unique supporting evidence IDs.")
            if any(evidence_id not in self.evidence_registry for evidence_id in evidence_refs):
                raise ValueError("Fulfilled obligation references missing evidence.")
        for obligation, evidence_refs in self.obligations.evidence_by_obligation.items():
            if obligation.startswith("overall.") and not any(
                evidence_id in root_evidence
                and root_evidence[evidence_id] == ("compare_periods", None)
                for evidence_id in evidence_refs
            ):
                raise ValueError("Overall obligations require root-scope comparison evidence.")
            if obligation.startswith("dimension."):
                dimension = obligation.removeprefix("dimension.").removesuffix(".breakdown")
                if not any(
                    evidence_id in root_evidence
                    and root_evidence[evidence_id] == ("breakdown_change", dimension)
                    for evidence_id in evidence_refs
                ):
                    raise ValueError("Dimension obligations require their root-scope breakdown evidence.")
        fulfilled_evidence_ids = {
            evidence_id
            for evidence_refs in self.obligations.evidence_by_obligation.values()
            for evidence_id in evidence_refs
        }
        if any(
            record.validation.accepted
            and record.candidate.evidence_id in root_evidence
            and record.candidate.evidence_id not in fulfilled_evidence_ids
            for record in self.findings
        ):
            raise ValueError("Accepted root findings must support a fulfilled root obligation.")

        if self.execution_status == "succeeded":
            if self.errors:
                raise ValueError("A succeeded execution cannot contain operational errors.")
            if self.sufficiency_status is None:
                raise ValueError("A succeeded execution requires a sufficiency status.")
            if self.sufficiency_status == "completed":
                if self.goal_disposition != "supported_descriptive" or missing:
                    raise ValueError("Completed requires a supported descriptive goal and all obligations.")
                if self.clarification_request:
                    raise ValueError("Completed analysis cannot be waiting for clarification.")
            elif self.sufficiency_status == "partial":
                if self.goal_disposition != "supported_descriptive" or not fulfilled or not missing:
                    raise ValueError("Partial requires supported evidence plus at least one missing obligation.")
                if self.clarification_request:
                    raise ValueError("A user-blocking clarification must use needs_input.")
            elif self.sufficiency_status == "abstained":
                if self.clarification_request:
                    raise ValueError("A user-blocking clarification must use needs_input.")
                if any(
                    record.validation.accepted
                    and record.candidate.evidence_id in root_evidence
                    for record in self.findings
                ):
                    raise ValueError("Abstained analysis cannot publish accepted root findings.")
                if self.goal_disposition == "unresolved":
                    raise ValueError("An unresolved user-resolvable goal must use needs_input.")
                if self.goal_disposition == "unsupported_causal":
                    if "goal.causal_explanation" not in missing:
                        raise ValueError("Unsupported causal goals cannot fulfill a causal explanation obligation.")
                elif fulfilled:
                    raise ValueError("Abstained requires no fulfilled quantitative obligation.")
            elif self.sufficiency_status == "needs_input":
                if self.goal_disposition == "unsupported_causal" or not missing:
                    raise ValueError("needs_input requires a supported or unresolved goal with missing obligations.")
                if not self.clarification_request or not self.clarification_request.strip():
                    raise ValueError("needs_input requires a user-resolvable clarification request.")
                if self.goal_disposition == "unresolved":
                    if (
                        "goal.semantic_clarification" not in missing
                        or fulfilled
                        or self.accepted_finding_ids
                    ):
                        raise ValueError("Unresolved semantic goals cannot publish quantitative results before clarification.")
        else:
            if not self.errors:
                raise ValueError("Failed, cancelled, or expired execution requires an operational error.")
            if self.sufficiency_status is not None:
                raise ValueError("Operational failure is separate from analytical sufficiency.")
            if self.accepted_finding_ids:
                raise ValueError("Operational failure cannot publish accepted findings.")

        body = self.model_dump(mode="json", exclude={"content_fingerprint"})
        if set(body) != set(ARTIFACT_FINGERPRINT_FIELDS):
            raise ValueError("Artifact fingerprint field list must match the schema fields.")
        if fingerprint(body) != self.content_fingerprint:
            raise ValueError("Artifact content fingerprint mismatch.")
        return self


class Issue(Schema):
    code: str
    severity: Literal["error", "warning"]
    scope: str
    count: int = 1
    message: str


class ValidationReport(Versioned):
    analysis_readiness: Literal["ready", "blocked"]
    issues: list[Issue] = Field(default_factory=list)


def canonical(value: Schema | dict | list) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def fingerprint(value: Schema | dict | list) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()
