"""Persistence boundary for the authoritative validated analysis artifact."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .contracts import (
    TrustedAnalysisLoadContext,
    ValidatedAnalysisArtifact,
    canonical,
    fingerprint,
)
from .errors import BIError
from .finding_validation import (
    finalizer_block_finding_validation,
    trusted_scope_for_evidence_call,
    validate_candidate_finding,
)
from .store import RunStore

ANALYSIS_ARTIFACT_NAME = "validated_analysis.json"


class ValidatedAnalysisStore:
    """Read and write one T06 artifact in a run, without synthesizing a replacement."""

    def __init__(self, runs: RunStore):
        self.runs = runs

    def write(self, run_id: str, artifact: ValidatedAnalysisArtifact) -> None:
        """Persist a structurally valid T06 artifact through RunStore's atomic writer."""
        if not isinstance(artifact, ValidatedAnalysisArtifact):
            raise BIError("INVALID_ARTIFACT", "Only a validated analysis artifact can be written.")
        try:
            checked = ValidatedAnalysisArtifact.model_validate(artifact.model_dump(mode="json"))
        except ValidationError as error:
            raise self._invalid_artifact_error(error) from None
        self.runs.write(run_id, ANALYSIS_ARTIFACT_NAME, checked.model_dump(mode="json"))

    def load(
        self, run_id: str, trusted_context: TrustedAnalysisLoadContext
    ) -> ValidatedAnalysisArtifact:
        """Load only when current dependencies and fresh M1 verdicts agree."""
        try:
            context = TrustedAnalysisLoadContext.model_validate(trusted_context)
        except (ValidationError, TypeError, ValueError):
            raise BIError(
                "INVALID_TRUSTED_CONTEXT", "Current trusted analysis context is inconsistent."
            ) from None

        # Preserve RunStore's owner, retention and path checks before probing existence.
        self.runs.manifest(run_id)
        path = self.runs._path(run_id) / ANALYSIS_ARTIFACT_NAME
        if path.is_symlink():
            raise BIError("UNSAFE_PATH", "Managed artifacts must not be symbolic links.")
        if not path.exists():
            raise BIError(
                "ARTIFACT_MISSING",
                "Validated analysis artifact is missing; start a new run to create one.",
            )

        payload = self.runs.read(run_id, ANALYSIS_ARTIFACT_NAME)
        if not isinstance(payload, dict):
            raise BIError("INVALID_ARTIFACT", "Validated analysis artifact must be a JSON object.")
        if payload.get("schema_version") != "1.0" or payload.get("artifact_version") != "1.0":
            raise BIError(
                "LEGACY_ARTIFACT",
                "Artifact schema is legacy or unsupported; start a new run.",
            )

        try:
            artifact = ValidatedAnalysisArtifact.model_validate(payload)
        except ValidationError as error:
            raise self._invalid_artifact_error(error) from None

        self._check_current_dependencies(artifact, context)
        self._check_evidence_registry(artifact, context)
        self._revalidate_findings(artifact, context)
        return artifact

    @staticmethod
    def _invalid_artifact_error(error: ValidationError) -> BIError:
        messages = [item.get("msg", "") for item in error.errors(include_input=False)]
        combined = " ".join(messages).lower()
        if "content fingerprint mismatch" in combined:
            return BIError(
                "TAMPERED_ARTIFACT", "Artifact content fingerprint does not match its contents."
            )
        if "accepted ids" in combined:
            return BIError(
                "INVALID_ARTIFACT", "Accepted IDs do not match the finding verdict partition."
            )
        if "rejected ids" in combined:
            return BIError(
                "INVALID_ARTIFACT", "Rejected IDs do not match the finding verdict partition."
            )
        return BIError(
            "INVALID_ARTIFACT", "Validated analysis artifact violates its declared contract."
        )

    @staticmethod
    def _check_current_dependencies(
        artifact: ValidatedAnalysisArtifact, context: TrustedAnalysisLoadContext
    ) -> None:
        if artifact.dataset_hash != context.dataset_hash:
            raise BIError("STALE_ARTIFACT", "Artifact dependency changed: dataset_hash.")
        expected_contract = context.confirmed_contract_snapshot
        if (
            artifact.contract_fingerprint != fingerprint(expected_contract)
            or canonical(artifact.confirmed_contract_snapshot) != canonical(expected_contract)
        ):
            raise BIError(
                "STALE_ARTIFACT", "Artifact dependency changed: confirmed_contract_snapshot."
            )
        if (
            artifact.root_request_fingerprint != fingerprint(context.root_request)
            or canonical(artifact.root_request) != canonical(context.root_request)
        ):
            raise BIError("STALE_ARTIFACT", "Artifact dependency changed: root_request.")
        expected_scope = context.finding_context.root_scope
        if canonical(artifact.root_scope) != canonical(expected_scope):
            raise BIError("STALE_ARTIFACT", "Artifact dependency changed: root_scope.")
        if artifact.implementation_version != context.implementation_version:
            raise BIError("STALE_ARTIFACT", "Artifact dependency changed: implementation_version.")
        if artifact.validator_version != context.validator_version:
            raise BIError("STALE_ARTIFACT", "Artifact dependency changed: validator_version.")

    @staticmethod
    def _check_evidence_registry(
        artifact: ValidatedAnalysisArtifact, context: TrustedAnalysisLoadContext
    ) -> None:
        trusted = context.finding_context
        for evidence_id, evidence in artifact.evidence_registry.items():
            expected_call = trusted.evidence_calls.get(evidence_id)
            if expected_call is None:
                raise BIError(
                    "TAMPERED_ARTIFACT",
                    "Evidence registry contains an ID absent from the trusted execution context.",
                )
            body = {key: value for key, value in evidence.items() if key != "evidence_id"}
            if "EV_" + fingerprint(body)[:24] != evidence_id:
                raise BIError(
                    "TAMPERED_ARTIFACT", "Evidence registry content does not match its evidence ID."
                )
            try:
                expected_scope = trusted_scope_for_evidence_call(expected_call)
                evidence_scope = evidence.get("scope", {})
                scopes_match = canonical(evidence_scope) == canonical(expected_scope)
            except (AttributeError, TypeError, ValueError):
                raise BIError("TAMPERED_ARTIFACT", "Evidence registry scope is invalid.") from None
            if (
                evidence.get("dataset_hash") != trusted.dataset_hash
                or evidence.get("contract_fingerprint") != trusted.contract_fingerprint
                or evidence.get("tool") != expected_call.tool
                or not scopes_match
            ):
                raise BIError(
                    "TAMPERED_ARTIFACT",
                    "Evidence registry provenance does not match the trusted execution context.",
                )

    @staticmethod
    def _revalidate_findings(
        artifact: ValidatedAnalysisArtifact, context: TrustedAnalysisLoadContext
    ) -> None:
        evidence_results: list[dict[str, Any]] = list(artifact.evidence_registry.values())
        accepted_ids: list[str] = []
        rejected_ids: list[str] = []
        for record in artifact.findings:
            _, fresh_validation = validate_candidate_finding(
                record.candidate, evidence_results, context.finding_context
            )
            expected_validation = fresh_validation
            if artifact.execution_status != "succeeded":
                expected_validation = finalizer_block_finding_validation(
                    expected_validation, "EXECUTION_INCOMPLETE", "scope"
                )
            elif artifact.goal_disposition == "unresolved":
                expected_validation = finalizer_block_finding_validation(
                    expected_validation,
                    "SEMANTIC_CLARIFICATION_REQUIRED",
                    "interpretation",
                )
            elif (
                artifact.goal_disposition == "unsupported_causal"
                and record.candidate.evidence_id in artifact.root_evidence_ids
            ):
                expected_validation = finalizer_block_finding_validation(
                    expected_validation,
                    "CAUSAL_GOAL_OUTSIDE_SCOPE",
                    "interpretation",
                )
            if canonical(expected_validation) != canonical(record.validation):
                raise BIError(
                    "FINDING_REVALIDATION_FAILED",
                    f"Stored finding verdict differs from fresh validation for {record.candidate.finding_id}.",
                )
            if record.validation.accepted:
                accepted_ids.append(record.candidate.finding_id)
            else:
                rejected_ids.append(record.candidate.finding_id)

        if artifact.accepted_finding_ids != accepted_ids:
            raise BIError("INVALID_ARTIFACT", "Accepted IDs do not match fresh finding verdicts.")
        if artifact.rejected_finding_ids != rejected_ids:
            raise BIError("INVALID_ARTIFACT", "Rejected IDs do not match fresh finding verdicts.")
