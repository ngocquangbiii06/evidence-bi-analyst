"""Two optional one-call LLM stages, each with its own visible, budgeted local run."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from .contracts import DataPolicy, Schema, canonical, fingerprint
from .errors import BIError
from .provider import STAGE_INSTRUCTIONS, strict_schema
from .security import FORBIDDEN_TEXT
from .semantics import propose_semantics
from .workflow import verify_policy_source


class SemanticChoice(Schema):
    date_column_token: str | None
    date_format: Literal["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"] | None
    row_key_tokens: list[str] = Field(max_length=8)
    metric_column_token: str | None
    dimension_tokens: list[str] = Field(max_length=5)
    evidence_ids: list[str] = Field(max_length=30)
    questions: list[str] = Field(max_length=8)


class BIChoice(Schema):
    prominent_dimensions: list[str] = Field(max_length=2)
    emphasis: Literal["change", "trend"]
    evidence_ids: list[str] = Field(min_length=1, max_length=30)
    summary: str = Field(max_length=500)


def authorize_stage(dataset_hash: str, policy: DataPolicy, stage: str):
    if not policy.external_llm_enabled or policy.mode != "demo_cloud":
        raise BIError("EGRESS_DENIED", "External structured generation is disabled.")
    if stage not in policy.approved_stages:
        raise BIError("STAGE_DENIED", "This generation stage needs separate policy approval.")
    if policy.dataset_class not in {"synthetic", "public"}:
        raise BIError("DATA_CLASS_DENIED", "Cloud stages only accept approved demo data.")
    if dataset_hash not in policy.approved_dataset_hashes:
        raise BIError("DATASET_NOT_APPROVED", "Dataset is not approved for cloud processing.")
    if policy.approved_endpoint != "https://api.openai.com/v1/responses":
        raise BIError("ENDPOINT_DENIED", "No approved endpoint is configured.")


def _generate(
    store, dataset_hash, policy, adapter, stage, payload, schema_type, validate, *, policy_path=None
):
    policy_source = {
        "policy_source_path": str(Path(policy_path).absolute()) if policy_path else None
    }
    verify_policy_source(policy_source, policy)
    authorize_stage(dataset_hash, policy, stage)
    if getattr(adapter, "purpose", None) != stage:
        raise BIError("STAGE_DENIED", "Provider adapter is configured for a different stage.")
    serialized = canonical(payload)
    if len(serialized.encode()) > policy.max_payload_bytes:
        raise BIError("PAYLOAD_LIMIT", "Approved structured context is too large.")
    if FORBIDDEN_TEXT.search(serialized):
        raise BIError("SENSITIVE_TEXT", "Potentially sensitive content was blocked.")
    schema = strict_schema(schema_type)
    reserve = (
        (
            len(serialized.encode())
            + len(canonical(schema).encode())
            + len(STAGE_INSTRUCTIONS[stage].encode())
            + 2048
        )
        * policy.input_usd_per_million
        + policy.max_output_tokens * policy.output_usd_per_million
    ) / 1_000_000
    if adapter.is_live and (
        policy.max_cost_usd <= 0
        or min(policy.input_usd_per_million, policy.output_usd_per_million) <= 0
    ):
        raise BIError("BUDGET_REQUIRED", "Configure a finite stage budget and model token rates.")
    if adapter.is_live and reserve > policy.max_cost_usd:
        raise BIError("BUDGET_EXHAUSTED", "The single stage call exceeds its budget.")
    policy_hash = fingerprint(policy)
    run_id = store.create(
        ttl_hours=policy.ttl_hours,
        metadata={
            "stage": stage,
            "dataset_hash": dataset_hash,
            "policy_fingerprint": policy_hash,
            **policy_source,
        },
    )
    store.write(run_id, "data_policy.json", policy.model_dump(mode="json"))
    usage = {
        "model_calls": 1,
        "cost_reserved_usd": reserve,
        "actual_cost_usd": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
    }
    store.write(run_id, "stage_usage.json", usage)
    store.update(run_id, status="GENERATING")
    start = time.monotonic()
    try:
        reply = adapter.invoke(
            payload, schema, policy.max_output_tokens, min(45, policy.max_run_seconds)
        )
        verify_policy_source(policy_source, policy)
        usage.update(
            input_tokens=reply.input_tokens,
            output_tokens=reply.output_tokens,
            actual_cost_usd=(
                reply.input_tokens * policy.input_usd_per_million
                + reply.output_tokens * policy.output_usd_per_million
            )
            / 1_000_000,
        )
        if (
            fingerprint(policy) != policy_hash
            or fingerprint(store.read(run_id, "data_policy.json")) != policy_hash
        ):
            raise BIError("POLICY_CHANGED", "Stage policy changed while generating the proposal.")
        choice = schema_type.model_validate_json(reply.arguments)
        result = validate(choice)
        result.update(
            stage_run_id=run_id,
            mode="llm_proposal" if adapter.is_live else "test_adapter",
            dataset_hash=dataset_hash,
            policy_fingerprint=policy_hash,
        )
        store.write(run_id, "stage_result.json", result)
    except (ValidationError, ValueError, TypeError):
        store.update(run_id, status="FAILED", error_code="INVALID_PROPOSAL")
        raise BIError(
            "INVALID_PROPOSAL", "Stage returned an invalid structured proposal."
        ) from None
    except BIError as error:
        store.update(run_id, status="FAILED", error_code=error.code)
        raise
    finally:
        usage["elapsed_seconds"] = time.monotonic() - start
        store.write(run_id, "stage_usage.json", usage)
    store.update(run_id, status="COMPLETED", result_fingerprint=fingerprint(result))
    return result


def review_semantics(dataset, policy, store, adapter, *, policy_path=None):
    local = propose_semantics(dataset)
    columns = {c["column_token"]: c for c in local["profile"]["columns"]}
    authorize_stage(dataset.sha256, policy, "semantic_review")
    outgoing = []
    for token, column in columns.items():
        safe = {
            k: column[k]
            for k in [
                "column_token",
                "evidence_id",
                "null_count",
                "unique_nonnull_count",
                "nonnull_count",
                "sample_count",
                "type_scan",
                "uniqueness_scan",
                "date_valid_counts",
                "numeric_valid_count",
            ]
        }
        safe["approved_name"] = (
            column["name"] if column["name"] in policy.approved_schema_columns else None
        )
        outgoing.append(safe)
    payload = {
        "stage": "semantic_review",
        "row_count": local["profile"]["row_count"],
        "columns": outgoing,
    }

    def validate(choice):
        tokens = [
            t
            for t in [
                choice.date_column_token,
                choice.metric_column_token,
                *choice.row_key_tokens,
                *choice.dimension_tokens,
            ]
            if t is not None
        ]
        if not set(tokens).issubset(columns):
            raise BIError("UNKNOWN_COLUMN", "Semantic proposal refers to unavailable columns.")
        evidence = {columns[t]["evidence_id"] for t in tokens}
        known = {c["evidence_id"] for c in columns.values()}
        if not evidence.issubset(choice.evidence_ids) or not set(choice.evidence_ids).issubset(
            known
        ):
            raise BIError(
                "UNSUPPORTED_EVIDENCE", "Semantic proposal lacks corresponding profile evidence."
            )
        result = {
            k: local[k]
            for k in ["schema_version", "confirmed", "dataset_hash", "unknowns", "profile"]
        }
        result.update(
            method="llm_profile_review",
            mappings={
                "date_column": columns[choice.date_column_token]["name"]
                if choice.date_column_token
                else None,
                "date_format": choice.date_format,
                "row_key_columns": [columns[t]["name"] for t in choice.row_key_tokens],
                "metric_column": columns[choice.metric_column_token]["name"]
                if choice.metric_column_token
                else None,
                "dimension_columns": [columns[t]["name"] for t in choice.dimension_tokens],
            },
            evidence_ids=choice.evidence_ids,
            model_questions=choice.questions,
        )
        return result

    return _generate(
        store,
        dataset.sha256,
        policy,
        adapter,
        "semantic_review",
        payload,
        SemanticChoice,
        validate,
        policy_path=policy_path,
    )


def plan_bi(run_id, store, request, adapter):
    raise BIError(
        "STAGE_DISABLED",
        "LLM-selected Power BI layout is excluded from the frozen flagship scope.",
    )
