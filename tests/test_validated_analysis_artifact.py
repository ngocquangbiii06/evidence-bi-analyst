from copy import deepcopy

import pytest
from pydantic import ValidationError

from bi_analyst.contracts import (
    ARTIFACT_FINGERPRINT_FIELDS,
    ARTIFACT_LOAD_POLICY,
    AnalysisScope,
    CandidateFinding,
    FindingValidation,
    ValidatedAnalysisArtifact,
    canonical,
    fingerprint,
    required_obligation_ids,
)


def _finding_record(request, contract, evidence_id="EV_TOTAL", finding_id="F001"):
    metric = contract.metric(request.metric_id)
    scope = AnalysisScope(
        metric_id=request.metric_id,
        previous=request.previous,
        current=request.current,
        filters=request.filters,
        unit=metric.unit,
        scale=metric.scale,
    )
    candidate = CandidateFinding(
        finding_id=finding_id,
        claim_type="observation",
        evidence_id=evidence_id,
        scope=scope,
        text="Revenue changed between the requested periods.",
        field_refs=["data.previous.amount", "data.current.amount", "data.delta"],
        previous_minor=100,
        current_minor=300,
        delta_minor=200,
        previous="100",
        current="300",
        delta="200",
    )
    validation = FindingValidation(
        numerical="passed",
        evidence_linkage="passed",
        scope="passed",
        interpretation="passed",
        accepted=True,
    )
    return {
        "candidate": candidate.model_dump(mode="json"),
        "validation": validation.model_dump(mode="json"),
    }


def _artifact_payload(
    request,
    contract,
    *,
    goal_disposition="supported_descriptive",
    sufficiency_status="abstained",
    execution_status="succeeded",
    fulfilled=None,
    evidence_by_obligation=None,
    evidence_registry=None,
    root_evidence_ids=None,
    findings=None,
    investigation_trace=None,
    errors=None,
    clarification_request=None,
):
    contract_snapshot = contract.model_copy(deep=True)
    metric = contract_snapshot.metric(request.metric_id)
    root_scope = AnalysisScope(
        metric_id=request.metric_id,
        previous=request.previous,
        current=request.current,
        filters=request.filters,
        unit=metric.unit,
        scale=metric.scale,
    )
    findings = list(findings or [])
    evidence_registry = dict(evidence_registry or {})
    required = required_obligation_ids(request, goal_disposition)
    fulfilled = list(fulfilled or [])
    missing = [item for item in required if item not in set(fulfilled)]
    evidence_by_obligation = dict(evidence_by_obligation or {})
    root_evidence_ids = list(root_evidence_ids or [])
    for obligation, evidence_refs in evidence_by_obligation.items():
        for evidence_id in evidence_refs:
            evidence = evidence_registry.get(evidence_id)
            if not isinstance(evidence, dict):
                continue
            dimension = None
            tool = "compare_periods"
            if obligation.startswith("dimension."):
                dimension = obligation.removeprefix("dimension.").removesuffix(".breakdown")
                tool = "breakdown_change"
            if "scope" not in evidence:
                root_record = _root_comparison_record(request, contract, evidence_id)
                scope = root_record["scope"] | {"dimension": dimension}
                evidence["scope"] = scope
            evidence.setdefault("tool", tool)
            if evidence_id not in root_evidence_ids:
                root_evidence_ids.append(evidence_id)
    for evidence_id in root_evidence_ids:
        evidence = evidence_registry.get(evidence_id)
        if isinstance(evidence, dict) and "scope" not in evidence:
            root_record = _root_comparison_record(request, contract, evidence_id)
            evidence["scope"] = root_record["scope"]
            evidence.setdefault("tool", "compare_periods")
    accepted = [
        record["candidate"]["finding_id"]
        for record in findings
        if record["validation"]["accepted"]
    ]
    rejected = [
        record["candidate"]["finding_id"]
        for record in findings
        if not record["validation"]["accepted"]
    ]
    body = {
        "schema_version": "1.0",
        "artifact_version": "1.0",
        "validator_version": "1.0",
        "implementation_version": "1.0",
        "dataset_hash": "a" * 64,
        "confirmed_contract_snapshot": contract_snapshot.model_dump(mode="json"),
        "contract_fingerprint": fingerprint(contract_snapshot),
        "root_request": request.model_dump(mode="json"),
        "root_request_fingerprint": fingerprint(request),
        "root_scope": root_scope.model_dump(mode="json"),
        "mode": "deterministic",
        "goal_disposition": goal_disposition,
        "trace_revision": len(investigation_trace or []),
        "investigation_trace": list(investigation_trace or []),
        "prediction_revisions": [],
        "evidence_registry": evidence_registry,
        "root_evidence_ids": root_evidence_ids,
        "findings": findings,
        "accepted_finding_ids": accepted,
        "rejected_finding_ids": rejected,
        "obligations": {
            "required": required,
            "fulfilled": fulfilled,
            "missing": missing,
            "evidence_by_obligation": evidence_by_obligation,
        },
        "sufficiency_status": sufficiency_status,
        "limitations": [],
        "clarification_request": clarification_request,
        "execution_status": execution_status,
        "errors": list(errors or []),
        "usage": {
            "tool_calls": None,
            "model_calls": None,
            "elapsed_seconds": None,
            "input_tokens": None,
            "output_tokens": None,
            "cost_usd": None,
        },
    }
    # Producer example: compute the digest explicitly, then submit it for validation.
    body["content_fingerprint"] = fingerprint(body)
    return body


def _load(payload):
    return ValidatedAnalysisArtifact.model_validate_json(canonical(payload))


def _root_comparison_record(request, contract, evidence_id, data=None):
    metric = contract.metric(request.metric_id)
    scope = AnalysisScope(
        metric_id=request.metric_id,
        previous=request.previous,
        current=request.current,
        filters=request.filters,
        unit=metric.unit,
        scale=metric.scale,
    )
    return {
        "evidence_id": evidence_id,
        "tool": "compare_periods",
        "scope": scope.model_dump(mode="json"),
        "data": data or {},
    }


def _root_breakdown_record(request, contract, evidence_id, dimension):
    record = _root_comparison_record(request, contract, evidence_id)
    return {
        **record,
        "tool": "breakdown_change",
        "scope": record["scope"] | {"dimension": dimension},
    }


def _complete_root_evidence(request, contract):
    evidence = {
        "EV_TOTAL": _root_comparison_record(
            request,
            contract,
            "EV_TOTAL",
            {"previous_minor": 100, "current_minor": 300, "delta_minor": 200},
        )
    }
    root_evidence_ids = ["EV_TOTAL"]
    evidence_by_obligation = {}
    required = required_obligation_ids(request, "supported_descriptive")
    for obligation in required:
        if obligation.startswith("overall."):
            evidence_by_obligation[obligation] = ["EV_TOTAL"]
            continue
        dimension = obligation.removeprefix("dimension.").removesuffix(".breakdown")
        evidence_id = f"EV_{dimension.upper()}"
        evidence[evidence_id] = _root_breakdown_record(
            request, contract, evidence_id, dimension
        )
        root_evidence_ids.append(evidence_id)
        evidence_by_obligation[obligation] = [evidence_id]
    return evidence, root_evidence_ids, evidence_by_obligation


def test_completed_artifact_round_trips_with_verdict_derived_ids(
    request_spec, contract
):
    evidence, root_evidence_ids, evidence_by_obligation = _complete_root_evidence(
        request_spec, contract
    )
    record = _finding_record(request_spec, contract)
    required = required_obligation_ids(request_spec, "supported_descriptive")
    payload = _artifact_payload(
        request_spec,
        contract,
        sufficiency_status="completed",
        fulfilled=required,
        evidence_by_obligation=evidence_by_obligation,
        evidence_registry=evidence,
        root_evidence_ids=root_evidence_ids,
        findings=[record],
    )

    artifact = _load(payload)

    assert artifact.sufficiency_status == "completed"
    assert artifact.accepted_finding_ids == ["F001"]
    assert artifact.rejected_finding_ids == []
    body = artifact.model_dump(mode="json", exclude={"content_fingerprint"})
    assert set(body) == set(ARTIFACT_FINGERPRINT_FIELDS)
    assert artifact.content_fingerprint == fingerprint(body)


def test_e09_all_null_current_keeps_valid_previous_observation_partial(
    request_spec, contract
):
    evidence = {
        "EV_PREVIOUS": {
            "evidence_id": "EV_PREVIOUS",
            "data": {"period": "previous", "amount_minor": 12500, "valid_count": 2},
        },
        "EV_CURRENT": {
            "evidence_id": "EV_CURRENT",
            "data": {
                "period": "current",
                "row_count": 2,
                "valid_count": 0,
                "excluded_null_count": 2,
                "all_null": True,
            },
        },
    }
    required = required_obligation_ids(request_spec, "supported_descriptive")
    fulfilled = ["overall.previous_total"]
    artifact = _load(
        _artifact_payload(
            request_spec,
            contract,
            sufficiency_status="partial",
            fulfilled=fulfilled,
            evidence_by_obligation={"overall.previous_total": ["EV_PREVIOUS"]},
            evidence_registry=evidence,
        )
    )

    assert artifact.sufficiency_status == "partial"
    assert artifact.obligations.fulfilled == ["overall.previous_total"]
    assert artifact.obligations.missing == [item for item in required if item != "overall.previous_total"]
    assert artifact.evidence_registry["EV_PREVIOUS"]["data"]["amount_minor"] == 12500
    assert artifact.evidence_registry["EV_CURRENT"]["data"]["all_null"] is True
    assert artifact.accepted_finding_ids == []


def test_e08_unknown_coverage_without_answer_abstains(request_spec, contract):
    artifact = _load(
        _artifact_payload(
            request_spec,
            contract,
            sufficiency_status="abstained",
            evidence_registry={
                "EV_COVERAGE": {
                    "evidence_id": "EV_COVERAGE",
                    "coverage": {"confirmed": False, "status": "unverifiable"},
                    "current_rows": 0,
                }
            },
        )
    )

    assert artifact.sufficiency_status == "abstained"
    assert artifact.obligations.fulfilled == []
    assert artifact.obligations.missing == artifact.obligations.required
    assert artifact.accepted_finding_ids == []
    assert artifact.evidence_registry["EV_COVERAGE"]["coverage"]["status"] == "unverifiable"


def test_abstained_root_request_can_retain_accepted_narrow_scope_finding(
    dataset, contract, request_spec
):
    from bi_analyst.analytics import Analytics
    from bi_analyst.finding_validation import (
        build_candidate_findings,
        trusted_analysis_context,
        trusted_evidence_call,
        validate_candidate_finding,
    )

    narrow_request = request_spec.model_copy(
        update={"filters": {"Region": ["North"]}}
    )
    evidence = Analytics(dataset, contract).compare_periods(narrow_request)
    finding_context = trusted_analysis_context(
        dataset.sha256,
        contract,
        request_spec,
        {
            evidence["evidence_id"]: trusted_evidence_call(
                contract, narrow_request, "compare_periods"
            )
        },
    )
    candidate = build_candidate_findings([evidence])[0]
    _, validation = validate_candidate_finding(candidate, [evidence], finding_context)
    assert validation.accepted is True

    findings = [
        {
            "candidate": candidate.model_dump(mode="json"),
            "validation": validation.model_dump(mode="json"),
        }
    ]
    payload = _artifact_payload(
        request_spec,
        contract,
        sufficiency_status="abstained",
        evidence_registry={evidence["evidence_id"]: evidence},
        findings=findings,
    )

    artifact = _load(payload)

    assert artifact.sufficiency_status == "abstained"
    assert artifact.accepted_finding_ids == [candidate.finding_id]
    assert artifact.root_evidence_ids == []
    assert artifact.findings[0].candidate.scope.filters == {"Region": ["North"]}

    misclassified = deepcopy(payload)
    misclassified["root_evidence_ids"] = [evidence["evidence_id"]]
    misclassified["content_fingerprint"] = fingerprint(
        {key: value for key, value in misclassified.items() if key != "content_fingerprint"}
    )
    with pytest.raises(ValidationError, match="Root evidence must use the exact root scope"):
        _load(misclassified)


def test_e12_unresolved_mapping_requests_user_input(request_spec, contract):
    artifact = _load(
        _artifact_payload(
            request_spec,
            contract,
            goal_disposition="unresolved",
            sufficiency_status="needs_input",
            clarification_request="Please confirm the Revenue grain and mapping before calculation.",
            evidence_registry={
                "EV_MAPPING": {
                    "evidence_id": "EV_MAPPING",
                    "mapping": {"status": "ambiguous", "requires_user_choice": True},
                }
            },
        )
    )

    assert artifact.sufficiency_status == "needs_input"
    assert "goal.semantic_clarification" in artifact.obligations.required
    assert artifact.obligations.fulfilled == []
    assert artifact.clarification_request
    assert artifact.accepted_finding_ids == []


def test_needs_input_can_retain_partial_observation_while_awaiting_coverage_confirmation(
    request_spec, contract
):
    evidence = {
        "EV_PREVIOUS": {
            "evidence_id": "EV_PREVIOUS",
            "data": {"period": "previous", "amount_minor": 12500, "valid_count": 2},
        },
        "EV_COVERAGE": {
            "evidence_id": "EV_COVERAGE",
            "coverage": {
                "confirmed": False,
                "status": "unverifiable",
                "requires_user_confirmation": True,
            },
        },
    }
    artifact = _load(
        _artifact_payload(
            request_spec,
            contract,
            sufficiency_status="needs_input",
            fulfilled=["overall.previous_total"],
            evidence_by_obligation={"overall.previous_total": ["EV_PREVIOUS"]},
            evidence_registry=evidence,
            clarification_request="Please confirm current-period coverage before comparing the periods.",
        )
    )

    assert artifact.goal_disposition == "supported_descriptive"
    assert artifact.obligations.fulfilled == ["overall.previous_total"]
    assert "overall.current_total" in artifact.obligations.missing
    assert "overall.delta" in artifact.obligations.missing
    assert artifact.evidence_registry["EV_PREVIOUS"]["data"]["amount_minor"] == 12500
    assert artifact.clarification_request


def test_e12_unresolved_mapping_cannot_publish_quantitative_finding(request_spec, contract):
    record = _finding_record(request_spec, contract)
    payload = _artifact_payload(
        request_spec,
        contract,
        goal_disposition="unresolved",
        sufficiency_status="needs_input",
        clarification_request="Please confirm the Revenue mapping before calculation.",
        evidence_registry={
            "EV_TOTAL": {
                "evidence_id": "EV_TOTAL",
                "data": {"previous_minor": 100, "current_minor": 300, "delta_minor": 200},
            }
        },
        findings=[record],
    )

    with pytest.raises(ValidationError):
        _load(payload)


def test_needs_input_requires_a_missing_obligation_and_nonempty_clarification(
    request_spec, contract
):
    no_missing = required_obligation_ids(request_spec, "supported_descriptive")
    payloads = [
        _artifact_payload(
            request_spec,
            contract,
            sufficiency_status="needs_input",
            fulfilled=no_missing,
            evidence_by_obligation={item: ["EV_TOTAL"] for item in no_missing},
            evidence_registry={"EV_TOTAL": {"evidence_id": "EV_TOTAL"}},
            clarification_request="Please confirm coverage.",
        ),
        _artifact_payload(
            request_spec,
            contract,
            goal_disposition="unresolved",
            sufficiency_status="needs_input",
            clarification_request="   ",
        ),
        _artifact_payload(
            request_spec,
            contract,
            goal_disposition="unsupported_causal",
            sufficiency_status="needs_input",
            clarification_request="Please provide causal evidence.",
        ),
    ]

    for payload in payloads:
        with pytest.raises(ValidationError):
            _load(payload)


def test_unsupported_causal_root_goal_cannot_be_completed(request_spec, contract):
    causal_request = request_spec.model_copy(
        update={"question": "What caused Revenue to increase?"}
    )
    evidence, root_evidence_ids, evidence_by_obligation = _complete_root_evidence(
        causal_request, contract
    )
    quantitative = required_obligation_ids(causal_request, "supported_descriptive")
    payload = _artifact_payload(
        causal_request,
        contract,
        goal_disposition="unsupported_causal",
        sufficiency_status="completed",
        fulfilled=quantitative,
        evidence_by_obligation=evidence_by_obligation,
        evidence_registry=evidence,
        root_evidence_ids=root_evidence_ids,
    )

    with pytest.raises(ValidationError, match="Completed requires a supported descriptive goal"):
        _load(payload)


def test_accepted_finding_bool_cannot_override_failed_validator_state(request_spec, contract):
    evidence, root_evidence_ids, evidence_by_obligation = _complete_root_evidence(
        request_spec, contract
    )
    required = required_obligation_ids(request_spec, "supported_descriptive")
    record = _finding_record(request_spec, contract)
    record["validation"]["accepted"] = False
    payload = _artifact_payload(
        request_spec,
        contract,
        sufficiency_status="completed",
        fulfilled=required,
        evidence_by_obligation=evidence_by_obligation,
        evidence_registry=evidence,
        root_evidence_ids=root_evidence_ids,
        findings=[record],
    )

    with pytest.raises(ValidationError, match="Finding acceptance must match the validator check states"):
        _load(payload)


def test_operational_failure_has_errors_and_no_sufficiency(request_spec, contract):
    evidence = {
        "EV_PREVIOUS": {
            "evidence_id": "EV_PREVIOUS",
            "data": {"period": "previous", "amount_minor": 12500, "valid_count": 2},
        }
    }
    artifact = _load(
        _artifact_payload(
            request_spec,
            contract,
            goal_disposition="unresolved",
            sufficiency_status=None,
            execution_status="failed",
            fulfilled=["overall.previous_total"],
            evidence_by_obligation={"overall.previous_total": ["EV_PREVIOUS"]},
            evidence_registry=evidence,
            investigation_trace=[
                {
                    "revision": 1,
                    "kind": "tool_call",
                    "tool": "aggregate_metric",
                    "evidence_ids": ["EV_PREVIOUS"],
                    "finding_ids": [],
                }
            ],
            errors=[
                {
                    "code": "TOOL_TIMEOUT",
                    "stage": "tool",
                    "message": "Comparison tool exceeded its execution deadline.",
                }
            ],
        )
    )

    assert artifact.execution_status == "failed"
    assert artifact.sufficiency_status is None
    assert artifact.errors[0].code == "TOOL_TIMEOUT"
    assert artifact.obligations.fulfilled == ["overall.previous_total"]
    assert artifact.evidence_registry["EV_PREVIOUS"]["data"]["amount_minor"] == 12500
    assert artifact.investigation_trace[0].evidence_ids == ["EV_PREVIOUS"]
    assert artifact.accepted_finding_ids == []


def test_abstained_artifact_cannot_publish_accepted_quantitative_finding(
    request_spec, contract
):
    payload = _artifact_payload(
        request_spec,
        contract,
        sufficiency_status="abstained",
        evidence_registry={
            "EV_TOTAL": _root_comparison_record(
                request_spec,
                contract,
                "EV_TOTAL",
                {"previous_minor": 100, "current_minor": 300, "delta_minor": 200},
            )
        },
        root_evidence_ids=["EV_TOTAL"],
        findings=[_finding_record(request_spec, contract)],
    )

    with pytest.raises(ValidationError):
        _load(payload)


@pytest.mark.parametrize(
    "mutation",
    ["duplicate_candidate", "accepted_missing", "accepted_extra", "rejected_overlap"],
)
def test_finding_ids_cannot_form_inconsistent_partitions(
    request_spec, contract, mutation
):
    evidence = {
        "EV_TOTAL": {
            "evidence_id": "EV_TOTAL",
            "data": {"previous_minor": 100, "current_minor": 300, "delta_minor": 200},
        }
    }
    required = required_obligation_ids(request_spec, "supported_descriptive")
    payload = _artifact_payload(
        request_spec,
        contract,
        fulfilled=required,
        evidence_by_obligation={item: ["EV_TOTAL"] for item in required},
        evidence_registry=evidence,
        findings=[_finding_record(request_spec, contract)],
    )
    if mutation == "duplicate_candidate":
        payload["findings"].append(deepcopy(payload["findings"][0]))
    elif mutation == "accepted_missing":
        payload["accepted_finding_ids"] = []
    elif mutation == "accepted_extra":
        payload["accepted_finding_ids"].append("F999")
    else:
        payload["rejected_finding_ids"] = ["F001"]
    payload["content_fingerprint"] = fingerprint(
        {key: value for key, value in payload.items() if key != "content_fingerprint"}
    )

    with pytest.raises(ValidationError):
        _load(payload)


@pytest.mark.parametrize("mutation", ["narrow_required", "duplicate_required", "overlap"])
def test_obligations_cannot_be_narrowed_or_partitioned_inconsistently(
    request_spec, contract, mutation
):
    required = required_obligation_ids(request_spec, "supported_descriptive")
    payload = _artifact_payload(request_spec, contract)
    if mutation == "narrow_required":
        payload["obligations"]["required"] = required[:-1]
        payload["obligations"]["missing"] = required[:-1]
    elif mutation == "duplicate_required":
        payload["obligations"]["required"].append(required[0])
    else:
        payload["obligations"]["fulfilled"] = [required[0]]
    payload["content_fingerprint"] = fingerprint(
        {key: value for key, value in payload.items() if key != "content_fingerprint"}
    )

    with pytest.raises(ValidationError):
        _load(payload)


def test_legacy_stale_and_missing_policy_never_upgrades_or_synthesizes(
    request_spec, contract
):
    payload = _artifact_payload(request_spec, contract)
    legacy = deepcopy(payload)
    del legacy["artifact_version"]
    missing_trace = deepcopy(payload)
    del missing_trace["investigation_trace"]
    stale = deepcopy(payload)
    stale["dataset_hash"] = "b" * 64

    assert ARTIFACT_LOAD_POLICY == {
        "legacy": "reject_require_new_run",
        "stale": "reject_require_new_run",
        "missing": "report_missing_without_synthesis",
    }
    with pytest.raises(ValidationError):
        _load(legacy)
    with pytest.raises(ValidationError):
        _load(missing_trace)
    with pytest.raises(ValidationError, match="content fingerprint mismatch"):
        _load(stale)


def test_content_fingerprint_detects_any_canonical_field_change(request_spec, contract):
    payload = _artifact_payload(request_spec, contract)
    payload["limitations"].append("changed after producer fingerprint")

    with pytest.raises(ValidationError, match="content fingerprint mismatch"):
        _load(payload)
