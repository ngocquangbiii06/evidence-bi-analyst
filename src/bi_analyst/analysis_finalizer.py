"""Shared deterministic finalization for authoritative analysis artifacts."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from pydantic import ValidationError

from . import __version__
from .analysis_store import ValidatedAnalysisStore
from .contracts import (
    AnalysisExecutionError,
    AnalysisMode,
    AnalysisRequest,
    AnalysisScope,
    AnalysisTraceEvent,
    AnalysisUsage,
    ArtifactFinding,
    BusinessContract,
    CandidateFinding,
    FindingValidation,
    GoalDisposition,
    TrustedAnalysisContext,
    TrustedAnalysisLoadContext,
    TrustedEvidenceCall,
    ValidatedAnalysisArtifact,
    canonical,
    fingerprint,
    required_obligation_ids,
)
from .errors import BIError
from .finding_validation import (
    build_candidate_findings,
    finalizer_block_finding_validation,
    trusted_analysis_context,
    trusted_scope_for_evidence_call,
    trusted_scope_for_request,
    validate_candidate_findings,
)
from .store import RunStore

IMPLEMENTATION_VERSION = __version__
VALIDATOR_VERSION = "1.0"
_CAUSAL_QUESTION = re.compile(
    r"\b(?:caus(?:e|es|ed|ing|al|ality|ation)|why)\b", re.IGNORECASE
)


# Vietnamese causal wording, matched on diacritic-folded lowercase text so that
# precomposed/decomposed Unicode and unaccented typing are treated alike.
_CAUSAL_QUESTION_VI = re.compile(
    r"\b(?:vi\s+sao|tai\s+sao|nguyen\s+nhan|nguyen\s+(?:do|co)|l[yi]\s+do)\b"
)

# "do/vì đâu" must not be folded: folding would make "đâu" (where) equal to "đầu"
# (head/first), which appears in descriptive questions such as "đầu kỳ" or "đầu mối".
# Matched on NFC lowercase text with diacritics; the bare "dau" is accepted only when
# the user literally typed it unaccented.
_CAUSAL_WHERE_VI = re.compile(r"\b(?:do|v[iì])\s+(?:đâu|dau)\b")


def _normalize_vietnamese(text: str) -> str:
    return unicodedata.normalize("NFC", text.casefold())


def _fold_vietnamese(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.casefold())
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.replace("đ", "d")


def goal_disposition_for_request(request: AnalysisRequest) -> GoalDisposition:
    """Apply the bounded unsupported-causality gate before either caller finalizes."""
    question = request.question
    if (
        _CAUSAL_QUESTION.search(question)
        or _CAUSAL_QUESTION_VI.search(_fold_vietnamese(question))
        or _CAUSAL_WHERE_VI.search(_normalize_vietnamese(question))
    ):
        return "unsupported_causal"
    return "supported_descriptive"


def trusted_analysis_load_context(
    dataset_hash: str,
    contract: BusinessContract,
    request: AnalysisRequest,
    evidence_calls: dict[str, TrustedEvidenceCall | dict[str, Any]],
) -> TrustedAnalysisLoadContext:
    """Build the current loader context from caller-owned run dependencies."""
    finding_context = trusted_analysis_context(dataset_hash, contract, request, evidence_calls)
    return TrustedAnalysisLoadContext(
        dataset_hash=dataset_hash,
        confirmed_contract_snapshot=contract,
        root_request=request,
        implementation_version=IMPLEMENTATION_VERSION,
        validator_version=VALIDATOR_VERSION,
        finding_context=finding_context,
    )


def finalize_analysis(
    store: RunStore,
    run_id: str,
    request: AnalysisRequest,
    contract: BusinessContract,
    dataset_hash: str,
    *,
    mode: AnalysisMode,
    results: list[dict[str, Any]],
    evidence_calls: dict[str, TrustedEvidenceCall | dict[str, Any]],
    investigation_trace: list[AnalysisTraceEvent | dict[str, Any]] | None = None,
    prediction_revisions: list[int] | None = None,
    goal_disposition: GoalDisposition = "supported_descriptive",
    execution_status: str = "succeeded",
    errors: list[AnalysisExecutionError | dict[str, Any]] | None = None,
    usage: AnalysisUsage | dict[str, Any] | None = None,
    limitations: list[str] | None = None,
    clarification_request: str | None = None,
) -> ValidatedAnalysisArtifact:
    """Validate every candidate, derive root obligations, then atomically persist one artifact."""
    if execution_status not in {"succeeded", "failed", "cancelled", "expired"}:
        raise BIError("INVALID_EXECUTION_STATUS", "Analysis execution outcome is invalid.")
    try:
        checked_request = AnalysisRequest.model_validate(request)
        checked_contract = BusinessContract.model_validate(contract)
        checked_calls = {
            evidence_id: TrustedEvidenceCall.model_validate(call)
            for evidence_id, call in evidence_calls.items()
        }
        context = trusted_analysis_context(
            dataset_hash, checked_contract, checked_request, checked_calls
        )
    except (ValidationError, TypeError, ValueError):
        raise BIError(
            "INVALID_TRUSTED_CONTEXT", "Current analysis context is inconsistent."
        ) from None

    normalized_results = [result for result in results if isinstance(result, dict)]
    evidence_registry: dict[str, dict[str, Any]] = {}
    for result in normalized_results:
        evidence_id = result.get("evidence_id")
        if not isinstance(evidence_id, str):
            continue
        existing = evidence_registry.get(evidence_id)
        if existing is not None and canonical(existing) != canonical(result):
            raise BIError("EVIDENCE_ID_COLLISION", "Evidence ID resolves to conflicting results.")
        evidence_registry[evidence_id] = result

    candidates = build_candidate_findings(normalized_results)
    finding_records = validate_candidate_findings(candidates, normalized_results, context)
    findings = [
        ArtifactFinding(
            candidate=CandidateFinding.model_validate(
                {key: value for key, value in record.items() if key not in {"validation", "validation_method"}}
            ),
            validation=FindingValidation.model_validate(record["validation"]),
        )
        for record in finding_records
    ]

    root_evidence_ids = _root_evidence_ids(
        normalized_results,
        context,
        checked_request,
        checked_contract,
        dataset_hash,
    )
    if execution_status != "succeeded":
        findings = _block_accepted_findings(findings, "EXECUTION_INCOMPLETE", "scope")
    elif goal_disposition == "unresolved":
        findings = _block_accepted_findings(
            findings, "SEMANTIC_CLARIFICATION_REQUIRED", "interpretation"
        )
    elif goal_disposition == "unsupported_causal":
        findings = _block_root_findings(findings, set(root_evidence_ids))

    required = required_obligation_ids(checked_request, goal_disposition)
    fulfilled, evidence_by_obligation = _fulfilled_obligations(
        checked_request,
        normalized_results,
        root_evidence_ids,
        findings,
        goal_disposition,
        execution_status,
    )
    missing = [item for item in required if item not in set(fulfilled)]
    if execution_status != "succeeded":
        sufficiency_status = None
    elif goal_disposition == "unresolved":
        sufficiency_status = "needs_input"
    elif goal_disposition == "unsupported_causal":
        sufficiency_status = "abstained"
    elif clarification_request:
        sufficiency_status = "needs_input"
    elif not fulfilled:
        sufficiency_status = "abstained"
    elif missing:
        sufficiency_status = "partial"
    else:
        sufficiency_status = "completed"

    if execution_status != "succeeded":
        fulfilled = []
        evidence_by_obligation = {}
        missing = list(required)

    root_scope = trusted_scope_for_request(checked_contract, checked_request)
    typed_trace = _typed_trace(
        investigation_trace,
        normalized_results,
        candidates,
        evidence_registry,
    )
    usage_record = _usage_record(usage, len(normalized_results))
    error_records = _error_records(errors or [])
    limitation_records = list(limitations or [])
    if goal_disposition == "unsupported_causal":
        limitation_records.append(
            "Causal inference is outside the supported analysis scope."
        )
    if execution_status != "succeeded" and not error_records:
        raise BIError(
            "INVALID_EXECUTION_ERROR", "An operational failure requires a recorded error."
        )

    body = {
        "schema_version": "1.0",
        "artifact_version": "1.0",
        "validator_version": VALIDATOR_VERSION,
        "implementation_version": IMPLEMENTATION_VERSION,
        "dataset_hash": dataset_hash,
        "confirmed_contract_snapshot": checked_contract.model_dump(mode="json"),
        "contract_fingerprint": fingerprint(checked_contract),
        "root_request": checked_request.model_dump(mode="json"),
        "root_request_fingerprint": fingerprint(checked_request),
        "root_scope": root_scope.model_dump(mode="json"),
        "mode": mode,
        "goal_disposition": goal_disposition,
        "trace_revision": typed_trace[-1].revision if typed_trace else 0,
        "investigation_trace": [event.model_dump(mode="json") for event in typed_trace],
        "prediction_revisions": list(prediction_revisions or []),
        "evidence_registry": evidence_registry,
        "root_evidence_ids": root_evidence_ids,
        "findings": [record.model_dump(mode="json") for record in findings],
        "accepted_finding_ids": [
            record.candidate.finding_id for record in findings if record.validation.accepted
        ],
        "rejected_finding_ids": [
            record.candidate.finding_id for record in findings if not record.validation.accepted
        ],
        "obligations": {
            "required": required,
            "fulfilled": fulfilled,
            "missing": missing,
            "evidence_by_obligation": evidence_by_obligation,
        },
        "sufficiency_status": sufficiency_status,
        "limitations": limitation_records,
        "clarification_request": (
            None if goal_disposition == "unsupported_causal" else clarification_request
        ),
        "execution_status": execution_status,
        "errors": [error.model_dump(mode="json") for error in error_records],
        "usage": usage_record.model_dump(mode="json"),
    }
    body["content_fingerprint"] = fingerprint(body)
    try:
        artifact = ValidatedAnalysisArtifact.model_validate(body)
    except ValidationError:
        raise BIError(
            "FINALIZATION_FAILED", "Analysis output did not satisfy the authoritative artifact contract."
        ) from None
    ValidatedAnalysisStore(store).write(run_id, artifact)
    return artifact


def compatibility_report(
    artifact: ValidatedAnalysisArtifact,
    run_id: str,
    *,
    predictions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Render the existing report shape only from the validated artifact."""
    status_by_sufficiency = {
        "completed": "COMPLETED",
        "partial": "PARTIAL",
        "abstained": "ABSTAINED",
        "needs_input": "NEEDS_INPUT",
    }
    if artifact.execution_status == "succeeded":
        status = status_by_sufficiency[artifact.sufficiency_status]
    else:
        status = {
            "failed": "FAILED",
            "cancelled": "CANCELLED",
            "expired": "EXPIRED",
        }[artifact.execution_status]
    findings = [
        record.candidate.model_dump(mode="json")
        | {"validation": record.validation.model_dump(mode="json")}
        for record in artifact.findings
    ]
    ordered_evidence_ids = []
    seen_evidence_ids = set()
    for event in artifact.investigation_trace:
        for evidence_id in event.evidence_ids:
            if evidence_id in artifact.evidence_registry and evidence_id not in seen_evidence_ids:
                ordered_evidence_ids.append(evidence_id)
                seen_evidence_ids.add(evidence_id)
    ordered_evidence_ids.extend(
        sorted(set(artifact.evidence_registry) - seen_evidence_ids)
    )
    errors = [error.model_dump(mode="json") for error in artifact.errors]
    usage = artifact.usage.model_dump(mode="json")
    return {
        "schema_version": artifact.schema_version,
        "run_id": run_id,
        "mode": artifact.mode,
        "status": status,
        "request": artifact.root_request.model_dump(mode="json"),
        "results": [artifact.evidence_registry[item] for item in ordered_evidence_ids],
        "findings": findings,
        "trace": [event.model_dump(mode="json") for event in artifact.investigation_trace],
        "predictions": list(predictions or []),
        "error": errors[0] if errors else None,
        "next_question": artifact.clarification_request,
        "limitations": list(artifact.limitations),
        "usage": {
            "model_calls": usage["model_calls"],
            "tool_calls": usage["tool_calls"],
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "actual_cost_usd": usage["cost_usd"],
            "elapsed_seconds": usage["elapsed_seconds"],
        },
        "sufficiency_status": artifact.sufficiency_status,
        "root_evidence_ids": list(artifact.root_evidence_ids),
        "validated_analysis_fingerprint": artifact.content_fingerprint,
    }


def _root_evidence_ids(
    results: list[dict[str, Any]],
    context: TrustedAnalysisContext,
    request: AnalysisRequest,
    contract: BusinessContract,
    dataset_hash: str,
) -> list[str]:
    root_scope = trusted_scope_for_request(contract, request)
    accepted: list[str] = []
    for result in results:
        evidence_id = result.get("evidence_id")
        if not isinstance(evidence_id, str) or not _matches_trusted_call(
            result, evidence_id, context, dataset_hash
        ):
            continue
        try:
            scope = AnalysisScope.model_validate(result.get("scope", {}))
        except (TypeError, ValueError):
            continue
        same_scope = (
            scope.metric_id == root_scope.metric_id
            and scope.previous == root_scope.previous
            and scope.current == root_scope.current
            and canonical(scope.filters) == canonical(root_scope.filters)
            and scope.unit == root_scope.unit
            and scope.scale == root_scope.scale
        )
        if not same_scope:
            continue
        if result.get("tool") == "compare_periods" and scope.dimension is None:
            accepted.append(evidence_id)
        elif result.get("tool") == "breakdown_change" and scope.dimension in request.dimensions:
            accepted.append(evidence_id)
    return list(dict.fromkeys(accepted))


def _matches_trusted_call(
    result: dict[str, Any],
    evidence_id: str,
    context: TrustedAnalysisContext,
    dataset_hash: str,
) -> bool:
    call = context.evidence_calls.get(evidence_id)
    if call is None:
        return False
    body = {key: value for key, value in result.items() if key != "evidence_id"}
    try:
        actual_scope = result.get("scope", {})
        expected_scope = trusted_scope_for_evidence_call(call)
        return bool(
            result.get("evidence_id") == "EV_" + fingerprint(body)[:24]
            and result.get("dataset_hash") == dataset_hash
            and result.get("contract_fingerprint") == context.contract_fingerprint
            and result.get("tool") == call.tool
            and canonical(actual_scope) == canonical(expected_scope)
        )
    except (AttributeError, TypeError, ValueError):
        return False


def _fulfilled_obligations(
    request: AnalysisRequest,
    results: list[dict[str, Any]],
    root_evidence_ids: list[str],
    findings: list[ArtifactFinding],
    goal_disposition: GoalDisposition,
    execution_status: str,
) -> tuple[list[str], dict[str, list[str]]]:
    if execution_status != "succeeded" or goal_disposition == "unresolved":
        return [], {}
    by_id = {result.get("evidence_id"): result for result in results}
    accepted_by_evidence: dict[str, list[ArtifactFinding]] = {}
    for record in findings:
        if record.validation.accepted:
            accepted_by_evidence.setdefault(record.candidate.evidence_id, []).append(record)

    fulfilled: list[str] = []
    evidence_by_obligation: dict[str, list[str]] = {}
    comparisons = [
        evidence_id
        for evidence_id in root_evidence_ids
        if by_id.get(evidence_id, {}).get("tool") == "compare_periods"
    ]
    root_comparison = comparisons[0] if comparisons else None
    comparison = by_id.get(root_comparison, {}) if root_comparison else {}
    data = comparison.get("data", {})
    previous = data.get("previous", {}) if isinstance(data, dict) else {}
    current = data.get("current", {}) if isinstance(data, dict) else {}
    previous_minor = previous.get("amount_minor") if isinstance(previous, dict) else None
    current_minor = current.get("amount_minor") if isinstance(current, dict) else None
    delta_minor = data.get("delta_minor") if isinstance(data, dict) else None

    if root_comparison and _is_minor_value(previous_minor):
        fulfilled.append("overall.previous_total")
        evidence_by_obligation["overall.previous_total"] = [root_comparison]
    if root_comparison and _is_minor_value(current_minor):
        fulfilled.append("overall.current_total")
        evidence_by_obligation["overall.current_total"] = [root_comparison]
    comparison_findings = accepted_by_evidence.get(root_comparison, []) if root_comparison else []
    delta_is_valid = (
        root_comparison is not None
        and _is_minor_value(previous_minor)
        and _is_minor_value(current_minor)
        and _is_minor_value(delta_minor)
        and delta_minor == current_minor - previous_minor
        and any(record.candidate.claim_type == "observation" for record in comparison_findings)
    )
    if delta_is_valid:
        fulfilled.append("overall.delta")
        evidence_by_obligation["overall.delta"] = [root_comparison]

    for dimension in request.dimensions:
        obligation = f"dimension.{dimension}.breakdown"
        breakdown_ids = [
            evidence_id
            for evidence_id in root_evidence_ids
            if by_id.get(evidence_id, {}).get("tool") == "breakdown_change"
            and by_id[evidence_id].get("scope", {}).get("dimension") == dimension
        ]
        valid_breakdown_id = next(
            (
                evidence_id
                for evidence_id in breakdown_ids
                if _valid_root_breakdown(by_id[evidence_id], accepted_by_evidence)
            ),
            None,
        )
        if valid_breakdown_id:
            fulfilled.append(obligation)
            evidence_by_obligation[obligation] = [valid_breakdown_id]

    if goal_disposition == "unsupported_causal":
        return [], {}
    required = required_obligation_ids(request, goal_disposition)
    fulfilled_set = set(fulfilled)
    return [item for item in required if item in fulfilled_set], evidence_by_obligation


def _valid_root_breakdown(
    result: dict[str, Any], accepted_by_evidence: dict[str, list[ArtifactFinding]]
) -> bool:
    data = result.get("data")
    if not isinstance(data, dict) or data.get("numerical_validation") != "passed":
        return False
    groups = data.get("groups")
    if not isinstance(groups, list):
        return False
    if any(not isinstance(group, dict) or not _is_minor_value(group.get("delta_minor")) for group in groups):
        return False
    records = accepted_by_evidence.get(result.get("evidence_id"), [])
    return len(records) == len(groups) and all(
        record.candidate.claim_type == "contribution" for record in records
    )


def _block_accepted_findings(
    findings: list[ArtifactFinding], reason: str, state_field: str
) -> list[ArtifactFinding]:
    blocked = []
    for record in findings:
        blocked.append(
            ArtifactFinding(
                candidate=record.candidate,
                validation=finalizer_block_finding_validation(
                    record.validation, reason, state_field
                ),
            )
        )
    return blocked


def _block_root_findings(
    findings: list[ArtifactFinding], root_evidence_ids: set[str]
) -> list[ArtifactFinding]:
    blocked = []
    for record in findings:
        blocked.append(
            ArtifactFinding(
                candidate=record.candidate,
                validation=(
                    finalizer_block_finding_validation(
                        record.validation,
                        "CAUSAL_GOAL_OUTSIDE_SCOPE",
                        "interpretation",
                    )
                    if record.candidate.evidence_id in root_evidence_ids
                    else record.validation
                ),
            )
        )
    return blocked


def _typed_trace(
    events: list[AnalysisTraceEvent | dict[str, Any]] | None,
    results: list[dict[str, Any]],
    candidates: list[CandidateFinding],
    evidence_registry: dict[str, dict[str, Any]],
) -> list[AnalysisTraceEvent]:
    if events is None:
        parsed = []
        for index, result in enumerate(results, start=1):
            evidence_id = result.get("evidence_id")
            if not isinstance(evidence_id, str) or evidence_id not in evidence_registry:
                continue
            parsed.append(
                AnalysisTraceEvent(
                    revision=len(parsed) + 1,
                    kind="tool_call",
                    tool=result.get("tool"),
                    evidence_ids=[evidence_id],
                )
            )
    else:
        try:
            parsed = [AnalysisTraceEvent.model_validate(event) for event in events]
        except (ValidationError, TypeError, ValueError):
            raise BIError("INVALID_ANALYSIS_TRACE", "Investigation trace is invalid.") from None

    candidate_ids_by_evidence: dict[str, list[str]] = {}
    for candidate in candidates:
        candidate_ids_by_evidence.setdefault(candidate.evidence_id, []).append(candidate.finding_id)
    normalized = []
    next_revision = 1
    for event in parsed:
        finding_ids = list(dict.fromkeys(event.finding_ids))
        for evidence_id in event.evidence_ids:
            finding_ids.extend(candidate_ids_by_evidence.get(evidence_id, []))
        normalized.append(
            event.model_copy(
                update={
                    "revision": next_revision,
                    "finding_ids": list(dict.fromkeys(finding_ids)),
                }
            )
        )
        next_revision += 1
    return normalized


def _usage_record(usage: AnalysisUsage | dict[str, Any] | None, result_count: int) -> AnalysisUsage:
    if usage is None:
        return AnalysisUsage(tool_calls=result_count, model_calls=0)
    if isinstance(usage, AnalysisUsage):
        return usage
    normalized = {
        "tool_calls": usage.get("tool_calls", result_count),
        "model_calls": usage.get("model_calls", 0),
        "elapsed_seconds": usage.get("elapsed_seconds"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cost_usd": usage.get("cost_usd", usage.get("actual_cost_usd")),
    }
    try:
        return AnalysisUsage.model_validate(normalized)
    except (ValidationError, TypeError, ValueError):
        raise BIError("INVALID_ANALYSIS_USAGE", "Analysis usage record is invalid.") from None


def _error_records(
    errors: list[AnalysisExecutionError | dict[str, Any]],
) -> list[AnalysisExecutionError]:
    records = []
    for error in errors:
        if isinstance(error, AnalysisExecutionError):
            records.append(error)
            continue
        try:
            records.append(
                AnalysisExecutionError(
                    code=error["code"],
                    stage=error.get("stage", "analysis"),
                    message=error["message"],
                )
            )
        except (ValidationError, KeyError, TypeError, ValueError):
            raise BIError("INVALID_EXECUTION_ERROR", "Analysis execution error is invalid.") from None
    return records


def _is_minor_value(value: Any) -> bool:
    return type(value) is int
