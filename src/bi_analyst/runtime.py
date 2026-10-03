"""A bounded observe/act loop; execution and validation stay outside the model."""

from __future__ import annotations

import multiprocessing as mp
import time
from threading import Event

from pydantic import ValidationError

from .analysis_finalizer import (
    IMPLEMENTATION_VERSION,
    compatibility_report,
    finalize_analysis,
    goal_disposition_for_request,
    trusted_analysis_load_context,
)
from .analysis_store import ValidatedAnalysisStore
from .contracts import AnalysisRequest, AnalysisTraceEvent, canonical, fingerprint
from .errors import BIError
from .finding_validation import build_findings as build_findings
from .finding_validation import trusted_evidence_call, trusted_scope_for_evidence_call
from .hypotheses import evaluate_predictions, register_predictions
from .provider import INSTRUCTIONS, Action, Adapter, strict_schema
from .security import PayloadBuilder
from .store import RunStore
from .workflow import open_engine, verify_snapshot

_PREDICTION_REJECTION_FEEDBACK = {
    "source": "prediction_registration",
    "retryable": True,
    "guidance": "Submit a valid prediction registration; revisions use a new prediction_id.",
}


def _worker(send, engine, request, action):
    try:
        if action.tool == "compare_periods":
            result = engine.compare_periods(request)
        elif action.tool == "breakdown_change":
            result = engine.breakdown_change(request, action.dimension)
        elif action.tool == "aggregate_metric":
            result = engine.aggregate_metric(
                request.metric_id, getattr(request, action.period), request.filters
            )
        else:
            raise BIError("TOOL_DENIED", "Requested tool is not registered.")
        send.send({"result": result})
    except BIError as error:
        send.send({"error": error.as_dict()})
    except Exception:
        send.send({"error": {"code": "TOOL_FAILED", "message": "Tool execution failed safely."}})
    finally:
        send.close()


def execute_tool(engine, request, action, *, timeout=15, cancel: Event | None = None):
    context = mp.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(send, engine, request, action), daemon=True)
    process.start()
    send.close()
    deadline = time.monotonic() + timeout
    try:
        while True:
            if cancel and cancel.is_set():
                raise BIError("CANCELLED", "Run was cancelled.")
            if time.monotonic() >= deadline:
                raise BIError("TOOL_TIMEOUT", "Tool exceeded the execution deadline.")
            if receive.poll(min(0.05, max(0, deadline - time.monotonic()))):
                try:
                    message = receive.recv()
                except EOFError:
                    raise BIError("TOOL_FAILED", "Tool stopped without a result.") from None
                if "error" in message:
                    error = message["error"]
                    raise BIError(error["code"], error["message"])
                return message["result"]
            if not process.is_alive():
                raise BIError("TOOL_FAILED", "Tool stopped without a result.")
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=1)
        if process.is_alive():
            process.kill()
            process.join(timeout=1)
        receive.close()


class AgentRunner:
    def __init__(self, store: RunStore, adapter: Adapter):
        self.store = store
        self.adapter = adapter
        # Only the exact M5 transport can supply the reviewed synthetic profile.
        from .live_evaluation import M5OpenAIAdapter

        self.m5_reviewed_profile = (
            adapter.reviewed_profile if type(adapter) is M5OpenAIAdapter else None
        )
        self.m5_initial_hypothesis = (
            adapter.initial_hypothesis if type(adapter) is M5OpenAIAdapter else None
        )
        self.m5_report_presenter = (
            adapter.present_report if type(adapter) is M5OpenAIAdapter else None
        )

    def run(
        self, run_id: str, request: AnalysisRequest, *, cancel: Event | None = None, resume=False
    ):
        engine, policy = open_engine(run_id, self.store)
        for dimension in request.dimensions:
            if dimension not in engine.contract.dimensions:
                raise BIError("UNKNOWN_DIMENSION", "Requested dimension is not registered.")
        if any(dimension not in engine.contract.dimensions for dimension in request.filters):
            raise BIError("INVALID_FILTER", "Filter dimension is not registered.")
        engine._prepare(request.metric_id)
        builder = PayloadBuilder(
            engine,
            request,
            policy,
            m5_reviewed_profile=self.m5_reviewed_profile,
            m5_initial_hypothesis=self.m5_initial_hypothesis,
        )
        # Even test adapters must satisfy the same egress policy. They never make network requests.
        builder.authorize_cloud()
        if self.adapter.is_live and (
            policy.max_cost_usd <= 0
            or policy.input_usd_per_million <= 0
            or policy.output_usd_per_million <= 0
        ):
            raise BIError(
                "BUDGET_REQUIRED",
                "Configure a finite budget and model token rates before live calls.",
            )
        if self.adapter.is_live or policy.allow_question:
            builder.authorize_reviewed_evaluation(
                endpoint=getattr(self.adapter, "ENDPOINT", None),
                stage=getattr(self.adapter, "purpose", None),
                model=getattr(self.adapter, "model", None),
            )
        schema = strict_schema(Action)
        snapshot = {
            "dataset": engine.dataset.sha256,
            "contract": fingerprint(engine.contract),
            "policy": fingerprint(policy),
            "request": fingerprint(request),
            "action_schema": fingerprint(schema),
            "prompt": fingerprint({"instructions": INSTRUCTIONS}),
            "implementation_version": IMPLEMENTATION_VERSION,
            "m5_initial_hypothesis_hash": (
                fingerprint({"initial_hypothesis": self.m5_initial_hypothesis})
                if self.m5_initial_hypothesis is not None
                else None
            ),
        }
        state = {
            "schema_version": "1.1",
            "run_id": run_id,
            "snapshot": snapshot,
            "results": [],
            "trusted_evidence_calls": {},
            "trusted_evidence_conflicts": [],
            "trace": [],
            "predictions": [],
            "status": "ANALYZING",
            "model_calls": 0,
            "tool_calls": 0,
            "transient_retries": 0,
            "repairs": 0,
            "cost_reserved_usd": 0.0,
            "actual_cost_usd": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "elapsed_seconds": 0.0,
            "adapter": self.adapter.name,
            "model": getattr(self.adapter, "model", None),
        }
        if resume:
            old = self.store.read(run_id, "agent_state.json")
            if fingerprint(old) != self.store.manifest(run_id).get("agent_state_fingerprint"):
                raise BIError("STALE_RUN", "Checkpoint integrity failed; start a fresh analysis.")
            if (
                old["snapshot"] != snapshot
                or old["adapter"] != self.adapter.name
                or old["model"] != getattr(self.adapter, "model", None)
            ):
                raise BIError("STALE_RUN", "Resume context changed; start a fresh analysis.")
            if old["status"] == "COMPLETED":
                evidence_calls = old.get("trusted_evidence_calls", {})
                if old.get("trusted_evidence_conflicts"):
                    evidence_calls = {
                        key: value
                        for key, value in evidence_calls.items()
                        if key not in old["trusted_evidence_conflicts"]
                    }
                load_context = trusted_analysis_load_context(
                    engine.dataset.sha256,
                    engine.contract,
                    request,
                    evidence_calls,
                )
                artifact = ValidatedAnalysisStore(self.store).load(run_id, load_context)
                report = compatibility_report(
                    artifact, run_id, predictions=old.get("predictions", [])
                )
                if self.m5_report_presenter is not None:
                    report = self.m5_report_presenter(report)
                self.store.write(run_id, "agent_report.json", report)
                self.store.update(
                    run_id,
                    status=report["status"],
                    report_fingerprint=fingerprint(report),
                )
                return report
            state = old
            state.setdefault("predictions", [])
            state.setdefault("trusted_evidence_calls", {})
            state.setdefault("trusted_evidence_conflicts", [])
            if "transient_retries" not in state or "repairs" not in state:
                raise BIError(
                    "STALE_RUN",
                    "Checkpoint is missing durable retry budget state; start a fresh analysis.",
                )
            state["status"] = "ANALYZING"
        self.store.update(
            run_id,
            status="ANALYZING",
            analysis_mode="live_agent" if self.adapter.is_live else "test_adapter",
        )
        start = time.monotonic()
        carried = state["elapsed_seconds"]
        seen = {
            item["action_fingerprint"] for item in state["trace"] if "action_fingerprint" in item
        }
        feedback = None
        feedback_details = None
        transient_retries = state["transient_retries"]
        repairs = state["repairs"]

        def checkpoint():
            state["elapsed_seconds"] = carried + time.monotonic() - start
            self.store.write(run_id, "agent_state.json", state)
            self.store.update(run_id, agent_state_fingerprint=fingerprint(state))

        def check_predictions(result):
            for event in evaluate_predictions(state["predictions"], result, builder):
                event["action_number"] = state["model_calls"]
                state["trace"].append(event)

        try:
            while True:
                checkpoint()
                # Re-read current artifacts on every turn; cached state cannot bypass revocation.
                current_manifest = self.store.manifest(run_id)
                if current_manifest["status"] == "CANCELLED" or (cancel and cancel.is_set()):
                    raise BIError("CANCELLED", "Run was cancelled.")
                verify_snapshot(run_id, self.store, engine, policy)
                if (
                    state["elapsed_seconds"] >= policy.max_run_seconds
                    or state["model_calls"] >= policy.max_model_calls
                ):
                    raise BIError("BUDGET_EXHAUSTED", "Run reached its time or model-call limit.")
                payload = builder.build(
                    state["results"], feedback_code=feedback,
                    feedback_details=feedback_details, predictions=state["predictions"]
                )
                # A conservative byte-based reservation. Actual provider usage is tracked separately.
                reserve = (
                    (
                        len(canonical(payload).encode())
                        + len(canonical(schema).encode())
                        + len(INSTRUCTIONS.encode())
                        + 2048
                    )
                    * policy.input_usd_per_million
                    + policy.max_output_tokens * policy.output_usd_per_million
                ) / 1_000_000
                if (
                    self.adapter.is_live
                    and state["cost_reserved_usd"] + reserve > policy.max_cost_usd
                ):
                    raise BIError(
                        "BUDGET_EXHAUSTED",
                        "Next request would exceed the configured estimated cost budget.",
                    )
                state["model_calls"] += 1
                state["cost_reserved_usd"] += reserve
                checkpoint()  # never retry an unrecorded potentially billed call after a crash
                try:
                    reply = self.adapter.invoke(
                        payload,
                        schema,
                        policy.max_output_tokens,
                        min(45, max(0.1, policy.max_run_seconds - state["elapsed_seconds"])),
                    )
                    state["input_tokens"] += reply.input_tokens
                    state["output_tokens"] += reply.output_tokens
                    state["actual_cost_usd"] += (
                        reply.input_tokens * policy.input_usd_per_million
                        + reply.output_tokens * policy.output_usd_per_million
                    ) / 1_000_000
                    action = Action.model_validate_json(reply.arguments)
                except (ValidationError, ValueError, TypeError):
                    if repairs >= 1:
                        raise BIError(
                            "INVALID_ACTION",
                            "Model repeatedly returned invalid structured actions.",
                        ) from None
                    repairs += 1
                    state["repairs"] = repairs
                    feedback = "INVALID_ACTION"
                    feedback_details = None
                    state["trace"].append({"event": "invalid_action", "code": feedback})
                    checkpoint()
                    continue
                except BIError as error:
                    if error.code == "PROVIDER_TRANSIENT" and transient_retries < 2:
                        transient_retries += 1
                        state["transient_retries"] = transient_retries
                        state["trace"].append({"event": "retry", "code": error.code})
                        checkpoint()
                        delay = min(
                            2 ** (transient_retries - 1),
                            max(0, policy.max_run_seconds - carried - (time.monotonic() - start)),
                        )
                        if cancel:
                            cancel.wait(delay)
                        else:
                            time.sleep(delay)
                        continue
                    raise
                if cancel and cancel.is_set():
                    raise BIError("CANCELLED", "Run was cancelled.")
                verify_snapshot(run_id, self.store, engine, policy)
                known = {result["evidence_id"] for result in state["results"]}
                if not set(action.evidence_ids).issubset(known):
                    state["trace"].extend(
                        [
                            {
                                "event": "invalid_evidence_proposal",
                                "code": "UNSUPPORTED_EVIDENCE",
                            },
                            {"event": "action_rejected", "code": "UNSUPPORTED_EVIDENCE"},
                        ]
                    )
                    checkpoint()
                    raise BIError(
                        "UNSUPPORTED_EVIDENCE", "Model referenced evidence that does not exist."
                    )
                child = request.model_copy(deep=True)
                child.filters = builder.decode_filters([f.model_dump() for f in action.filters])
                known_prediction_ids = {
                    item["prediction_id"] for item in state["predictions"]
                }
                try:
                    register_predictions(
                        state["predictions"], action.predictions, builder, child.filters
                    )
                except BIError as error:
                    # Keep the rejection trace bounded to a trusted internal code; do not
                    # persist model-supplied prediction fields or error text.
                    state["trace"].extend(
                        [
                            {"event": "prediction_rejected", "code": error.code},
                            {"event": "action_rejected", "code": error.code},
                        ]
                    )
                    if error.code != "INVALID_PREDICTION" or repairs >= 1:
                        checkpoint()
                        raise
                    repairs += 1
                    state["repairs"] = repairs
                    feedback = "INVALID_PREDICTION"
                    feedback_details = dict(_PREDICTION_REJECTION_FEEDBACK)
                    checkpoint()
                    continue
                for prediction in action.predictions:
                    if prediction.prediction_id not in known_prediction_ids:
                        state["trace"].append(
                            {
                                "event": "prediction_proposed",
                                "prediction_id": prediction.prediction_id,
                                "supersedes": prediction.supersedes,
                                "action_number": state["model_calls"],
                            }
                        )
                for prior_result in state["results"]:
                    check_predictions(prior_result)
                if action.kind == "ask":
                    state["status"] = "NEEDS_INPUT"
                    state["next_question"] = action.reason
                    state["trace"].append(
                        {"event": "ask", "evidence_ids": action.evidence_ids}
                    )
                    break
                if action.kind == "finish":
                    state["trace"].append(
                        {"event": "finish", "evidence_ids": action.evidence_ids}
                    )
                    root_evidence_ids = _trusted_root_evidence_ids(
                        state["results"],
                        state["trusted_evidence_calls"],
                        engine,
                        request,
                    )
                    root_results = [
                        result
                        for result in state["results"]
                        if result.get("evidence_id") in root_evidence_ids
                    ]
                    root_comparison_ids = {
                        result["evidence_id"]
                        for result in root_results
                        if result.get("tool") == "compare_periods"
                    }
                    root_breakdown_ids = {
                        result.get("scope", {}).get("dimension"): result["evidence_id"]
                        for result in root_results
                        if result.get("tool") == "breakdown_change"
                    }
                    required_root_citations = root_comparison_ids | {
                        root_breakdown_ids[dimension]
                        for dimension in request.dimensions
                        if dimension in root_breakdown_ids
                    }
                    all_root_scopes_observed = (
                        len(root_comparison_ids) > 0
                        and set(request.dimensions).issubset(root_breakdown_ids)
                    )
                    missing_citation_ids = sorted(
                        required_root_citations - set(action.evidence_ids)
                    )
                    if (
                        not all_root_scopes_observed
                        or missing_citation_ids
                    ):
                        feedback = "INSUFFICIENT_EVIDENCE"
                        feedback_details = {
                            "missing_root_comparison": not root_comparison_ids,
                            "missing_breakdown_dimensions": [
                                dimension for dimension in request.dimensions
                                if dimension not in root_breakdown_ids
                            ],
                            "missing_citation_ids": missing_citation_ids,
                        }
                        state["trace"].append({"event": "finish_rejected", "code": feedback})
                        continue
                    state["status"] = "COMPLETED"
                    break
                if state["tool_calls"] >= policy.max_tool_calls:
                    raise BIError("BUDGET_EXHAUSTED", "Tool-call budget exhausted.")
                if action.tool == "breakdown_change" and action.dimension not in request.dimensions:
                    raise BIError(
                        "DIMENSION_DENIED",
                        "Agent requested a dimension outside the analysis scope.",
                    )
                action_key = fingerprint(
                    {
                        "tool": action.tool,
                        "dimension": action.dimension,
                        "period": action.period,
                        "request": child.model_dump(mode="json", exclude={"question"}),
                    }
                )
                if action_key in seen:
                    feedback = "DUPLICATE_ACTION"
                    feedback_details = None
                    state["trace"].append({"event": "action_rejected", "code": feedback})
                    continue
                seen.add(action_key)
                state["tool_calls"] += 1
                state["trace"].append(
                    {
                        "event": "tool_requested",
                        "tool": action.tool,
                        "action_fingerprint": action_key,
                        "reason": action.reason,
                        "hypothesis": action.hypothesis,
                        "evidence_ids": action.evidence_ids,
                    }
                )
                checkpoint()
                # Policy/run revision checked again after the remote call and before execution.
                verify_snapshot(run_id, self.store, engine, policy)
                remaining = policy.max_run_seconds - carried - (time.monotonic() - start)
                if remaining <= 0:
                    raise BIError("BUDGET_EXHAUSTED", "Run time budget exhausted.")
                result = execute_tool(
                    engine,
                    child,
                    action,
                    timeout=min(policy.tool_timeout_seconds, remaining),
                    cancel=cancel,
                )
                state["results"].append(result)
                if action.tool in {"aggregate_metric", "compare_periods", "breakdown_change"}:
                    call = trusted_evidence_call(
                        engine.contract,
                        child,
                        action.tool,
                        dimension=action.dimension,
                        period=(
                            action.period
                            if action.tool == "aggregate_metric"
                            else None
                        ),
                    )
                    evidence_id = result["evidence_id"]
                    existing_call = state["trusted_evidence_calls"].get(evidence_id)
                    if evidence_id in state["trusted_evidence_conflicts"]:
                        pass
                    elif evidence_id not in state["trusted_evidence_calls"]:
                        state["trusted_evidence_calls"][evidence_id] = call.model_dump(
                            mode="json"
                        )
                    elif canonical(existing_call) != canonical(call):
                        state["trusted_evidence_calls"].pop(evidence_id, None)
                        state["trusted_evidence_conflicts"].append(evidence_id)
                check_predictions(result)
                state["trace"].append(
                    {
                        "event": "tool_completed",
                        "tool": action.tool,
                        "evidence_id": result["evidence_id"],
                    }
                )
                feedback = None
                feedback_details = None
        except BIError as error:
            state["status"] = (
                "CANCELLED"
                if error.code == "CANCELLED"
                else ("PARTIAL" if state["results"] else "FAILED")
            )
            state["error"] = error.as_dict()
        checkpoint()
        evidence_calls = state.get("trusted_evidence_calls", {})
        if state.get("trusted_evidence_conflicts"):
            evidence_calls = {
                key: value
                for key, value in evidence_calls.items()
                if key not in state["trusted_evidence_conflicts"]
            }
        execution_status = "succeeded"
        errors = []
        if state.get("error"):
            error = state["error"]
            execution_status = "cancelled" if error["code"] == "CANCELLED" else "failed"
            errors = [{"code": error["code"], "stage": "agent", "message": error["message"]}]
        goal_disposition = goal_disposition_for_request(request)
        if (
            goal_disposition == "supported_descriptive"
            and state["status"] == "NEEDS_INPUT"
        ):
            goal_disposition = "unresolved"
        artifact = finalize_analysis(
            self.store,
            run_id,
            request,
            engine.contract,
            engine.dataset.sha256,
            mode="live_agent" if self.adapter.is_live else "test_adapter",
            results=state["results"],
            evidence_calls=evidence_calls,
            investigation_trace=_analysis_trace(state["trace"], state["results"]),
            goal_disposition=goal_disposition,
            execution_status=execution_status,
            errors=errors,
            usage={
                "model_calls": state["model_calls"],
                "tool_calls": state["tool_calls"],
                "input_tokens": state["input_tokens"],
                "output_tokens": state["output_tokens"],
                "actual_cost_usd": state["actual_cost_usd"],
                "elapsed_seconds": state["elapsed_seconds"],
            },
            limitations=[
                "Sales observations and accounting contributions do not establish external causation.",
                "Model hypotheses and action summaries are unvalidated proposals; findings use registered templates.",
            ],
            clarification_request=state.get("next_question"),
        )
        report = compatibility_report(artifact, run_id, predictions=state["predictions"])
        if self.m5_report_presenter is not None:
            report = self.m5_report_presenter(report)
        self.store.write(run_id, "agent_report.json", report)
        self.store.update(
            run_id,
            status=report["status"],
            report_fingerprint=fingerprint(report),
        )
        return report


def _trusted_root_evidence_ids(results, evidence_calls, engine, request):
    """Return cited-scope candidates only for verified root comparison/breakdown calls."""
    root_ids = []
    for result in results:
        if not isinstance(result, dict):
            continue
        evidence_id = result.get("evidence_id")
        tool = result.get("tool")
        scope = result.get("scope")
        if not isinstance(evidence_id, str):
            continue
        if not isinstance(scope, dict):
            continue
        if tool == "compare_periods":
            expected_call = trusted_evidence_call(engine.contract, request, tool)
        elif tool == "breakdown_change":
            dimension = scope.get("dimension")
            if dimension not in request.dimensions:
                continue
            expected_call = trusted_evidence_call(
                engine.contract, request, tool, dimension=dimension
            )
        else:
            continue

        expected_call_data = expected_call.model_dump(mode="json")
        if canonical(evidence_calls.get(evidence_id)) != canonical(expected_call_data):
            continue
        if canonical(result.get("scope")) != canonical(
            trusted_scope_for_evidence_call(expected_call)
        ):
            continue
        body = {key: value for key, value in result.items() if key != "evidence_id"}
        if (
            evidence_id != "EV_" + fingerprint(body)[:24]
            or result.get("dataset_hash") != engine.dataset.sha256
            or result.get("contract_fingerprint") != fingerprint(engine.contract)
        ):
            continue
        root_ids.append(evidence_id)
    return list(dict.fromkeys(root_ids))


def _analysis_trace(state_trace, results):
    evidence_by_id = {result["evidence_id"]: result for result in results}
    events = []
    for entry in state_trace:
        source_event = entry.get("event")
        kind = None
        tool = None
        evidence_ids = []
        if source_event in {"tool_requested", "tool_completed"}:
            kind = "tool_call"
            tool = entry.get("tool")
            if entry.get("evidence_id") in evidence_by_id:
                evidence_ids = [entry["evidence_id"]]
            else:
                evidence_ids = [
                    evidence_id
                    for evidence_id in entry.get("evidence_ids", [])
                    if evidence_id in evidence_by_id
                ]
        elif source_event == "prediction_checked":
            kind = "prediction"
            evidence_id = entry.get("evidence_id")
            evidence_ids = [evidence_id] if evidence_id in evidence_by_id else []
        elif source_event == "finish":
            kind = "finish"
            evidence_ids = [
                evidence_id
                for evidence_id in entry.get("evidence_ids", [])
                if evidence_id in evidence_by_id
            ]
        elif source_event == "ask":
            kind = "ask"
            evidence_ids = [
                evidence_id
                for evidence_id in entry.get("evidence_ids", [])
                if evidence_id in evidence_by_id
            ]
        elif source_event in {
            "finish_rejected",
            "action_rejected",
            "invalid_action",
            "retry",
        }:
            kind = "rejection"
        if kind is None:
            continue
        events.append(
            AnalysisTraceEvent(
                revision=len(events) + 1,
                kind=kind,
                tool=tool,
                evidence_ids=evidence_ids,
            )
        )
    return events
