"""Application services shared by CLI and UI."""

import hashlib
import time
from pathlib import Path

from .analytics import Analytics
from .contracts import AnalysisRequest, BusinessContract, DataPolicy, ParserConfig, fingerprint
from .data import load_csv, load_csv_bytes, profile_dataset, read_csv_bytes
from .errors import BIError
from .store import RunStore, atomic_bytes


def ingest_run(
    source: Path,
    contract: BusinessContract,
    policy: DataPolicy,
    store: RunStore,
    parser: ParserConfig | None = None,
    *,
    policy_path: Path | None = None,
) -> str:
    run_id = store.create(
        ttl_hours=policy.ttl_hours,
        metadata={
            "contract_fingerprint": fingerprint(contract),
            "policy_fingerprint": fingerprint(policy),
            "policy_source_path": str(policy_path.absolute()) if policy_path else None,
        },
    )
    try:
        dataset = (
            load_csv_bytes(source, policy, parser)
            if isinstance(source, bytes)
            else load_csv(source, policy, parser)
        )
        profile, validation = profile_dataset(dataset, contract)
        atomic_bytes(store._path(run_id) / "dataset.csv", dataset.raw)
        store.write(run_id, "business_contract.json", contract.model_dump(mode="json"))
        store.write(run_id, "data_policy.json", policy.model_dump(mode="json"))
        store.write(run_id, "dataset_profile.json", profile)
        store.write(run_id, "validation_report.json", validation.model_dump(mode="json"))
        store.update(
            run_id,
            status="READY" if validation.analysis_readiness == "ready" else "NEEDS_INPUT",
            dataset_hash=dataset.sha256,
            dataset_id=dataset.dataset_id,
            parser=dataset.parser.model_dump(),
            analysis_readiness=validation.analysis_readiness,
        )
    except BIError as error:
        store.write(
            run_id,
            "validation_report.json",
            {"schema_version": "1.0", "analysis_readiness": "blocked", "issues": [error.as_dict()]},
        )
        store.update(run_id, status="FAILED", error_code=error.code)
        # The run can still be inspected; the input itself is never changed.
    return run_id


def open_engine(run_id: str, store: RunStore) -> tuple[Analytics, DataPolicy]:
    manifest = store.manifest(run_id)
    contract = BusinessContract.model_validate(store.read(run_id, "business_contract.json"))
    policy = DataPolicy.model_validate(store.read(run_id, "data_policy.json"))
    verify_policy_source(manifest, policy)
    if (
        fingerprint(contract) != manifest["contract_fingerprint"]
        or fingerprint(policy) != manifest["policy_fingerprint"]
    ):
        raise BIError("STALE_RUN", "Contract or policy changed; create a new run.")
    dataset = load_csv(
        store._path(run_id) / "dataset.csv", policy, ParserConfig.model_validate(manifest["parser"])
    )
    if dataset.sha256 != manifest["dataset_hash"]:
        raise BIError("DATASET_CHANGED", "Dataset no longer matches the recorded evidence source.")
    return Analytics(dataset, contract), policy


def verify_policy_source(manifest: dict, policy: DataPolicy) -> None:
    path = manifest.get("policy_source_path")
    if not path:
        return
    try:
        with Path(path).open("rb") as stream:
            content = stream.read(65_537)
        if len(content) > 65_536 or fingerprint(
            DataPolicy.model_validate_json(content)
        ) != fingerprint(policy):
            raise ValueError("Policy source changed")
    except (OSError, ValueError):
        raise BIError(
            "POLICY_CHANGED",
            "Operator policy changed or is unavailable; create a new run with reviewed settings.",
        ) from None


def verify_snapshot(run_id: str, store: RunStore, engine: Analytics, policy: DataPolicy) -> None:
    """Check revocation and source integrity without reparsing and reprofiling all rows."""
    manifest = store.manifest(run_id)
    verify_policy_source(manifest, policy)
    if (
        fingerprint(store.read(run_id, "business_contract.json")) != fingerprint(engine.contract)
        or fingerprint(store.read(run_id, "data_policy.json")) != fingerprint(policy)
        or manifest["contract_fingerprint"] != fingerprint(engine.contract)
        or manifest["policy_fingerprint"] != fingerprint(policy)
        or manifest["dataset_hash"] != engine.dataset.sha256
    ):
        raise BIError("STALE_RUN", "Dataset, contract or policy revision changed.")
    content = read_csv_bytes(store._path(run_id) / "dataset.csv", policy)
    if hashlib.sha256(content).hexdigest() != engine.dataset.sha256:
        raise BIError("DATASET_CHANGED", "Dataset changed after analysis started.")


def analyze_deterministic(run_id: str, store: RunStore, request: AnalysisRequest) -> dict:
    from .analysis_finalizer import (
        IMPLEMENTATION_VERSION,
        compatibility_report,
        finalize_analysis,
        goal_disposition_for_request,
    )
    from .finding_validation import (
        trusted_evidence_call,
    )
    from .provider import Action
    from .runtime import execute_tool

    engine, policy = open_engine(run_id, store)
    if any(dimension not in engine.contract.dimensions for dimension in request.dimensions):
        raise BIError("UNKNOWN_DIMENSION", "Requested dimension is not registered.")
    if any(dimension not in engine.contract.dimensions for dimension in request.filters):
        raise BIError("INVALID_FILTER", "Filter dimension is not registered.")
    engine._prepare(request.metric_id)
    goal_disposition = goal_disposition_for_request(request)
    store.update(
        run_id,
        status="ANALYZING",
        analysis_mode="deterministic",
        deterministic_execution_fingerprint=None,
    )
    start = time.monotonic()
    results = []
    evidence_calls = {}
    tool_calls = 0
    try:
        actions = [
            Action(kind="tool", tool="compare_periods", reason="Compare the selected periods.")
        ] + [
            Action(
                kind="tool",
                tool="breakdown_change",
                dimension=d,
                reason="Reconcile the requested dimension.",
            )
            for d in request.dimensions
        ]
        for action in actions:
            verify_snapshot(run_id, store, engine, policy)
            remaining = policy.max_run_seconds - (time.monotonic() - start)
            if remaining <= 0:
                raise BIError("BUDGET_EXHAUSTED", "Deterministic analysis reached its time budget.")
            expected_call = trusted_evidence_call(
                engine.contract,
                request,
                action.tool,
                dimension=action.dimension,
            )
            tool_calls += 1
            result = execute_tool(
                engine, request, action, timeout=min(policy.tool_timeout_seconds, remaining)
            )
            results.append(result)
            evidence_calls[result["evidence_id"]] = expected_call
    except BIError as error:
        execution_status = "cancelled" if error.code == "CANCELLED" else "failed"
        artifact = finalize_analysis(
            store,
            run_id,
            request,
            engine.contract,
            engine.dataset.sha256,
            mode="deterministic",
            results=results,
            evidence_calls=evidence_calls,
            goal_disposition=goal_disposition,
            execution_status=execution_status,
            errors=[{"code": error.code, "stage": "deterministic", "message": error.message}],
            usage={
                "tool_calls": tool_calls,
                "model_calls": 0,
                "elapsed_seconds": time.monotonic() - start,
            },
            limitations=[
                "Observed changes and accounting contributions do not establish external causation."
            ],
        )
        report = compatibility_report(artifact, run_id)
        store.write(run_id, "analysis_report.json", report)
        store.update(
            run_id,
            status=report["status"],
            report_fingerprint=fingerprint(report),
            error_code=error.code,
        )
        raise

    artifact = finalize_analysis(
        store,
        run_id,
        request,
        engine.contract,
        engine.dataset.sha256,
        mode="deterministic",
        results=results,
        evidence_calls=evidence_calls,
        goal_disposition=goal_disposition,
        usage={
            "tool_calls": tool_calls,
            "model_calls": 0,
            "elapsed_seconds": time.monotonic() - start,
        },
        limitations=[
            "Observed changes and accounting contributions do not establish external causation."
        ],
    )
    execution = {
        "schema_version": "1.0",
        "run_id": run_id,
        "mode": "deterministic",
        "status": "COMPLETED",
        "snapshot": {
            "dataset": engine.dataset.sha256,
            "contract": fingerprint(engine.contract),
            "policy": fingerprint(policy),
            "request": fingerprint(request),
            "implementation_version": IMPLEMENTATION_VERSION,
        },
        "results": results,
        "trusted_evidence_calls": {
            evidence_id: call.model_dump(mode="json")
            for evidence_id, call in evidence_calls.items()
        },
    }
    store.write(run_id, "deterministic_execution.json", execution)
    store.update(
        run_id, deterministic_execution_fingerprint=fingerprint(execution)
    )
    report = compatibility_report(artifact, run_id)
    store.write(run_id, "analysis_report.json", report)
    store.update(run_id, status=report["status"], report_fingerprint=fingerprint(report))
    return report
