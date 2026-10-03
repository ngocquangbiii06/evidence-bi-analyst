from copy import deepcopy
from decimal import Decimal

import pytest
from test_data import make_csv

from bi_analyst.analytics import Analytics
from bi_analyst.contracts import (
    AnalysisRequest,
    AnalysisScope,
    Period,
    TrustedAnalysisContext,
    TrustedEvidenceCall,
    fingerprint,
)
from bi_analyst.data import load_csv_bytes
from bi_analyst.finding_validation import (
    build_candidate_findings,
    trusted_analysis_context,
    trusted_evidence_call,
    validate_candidate_finding,
    validate_candidate_findings,
)
from bi_analyst.runtime import build_findings


def _rehash_evidence(result):
    body = {key: value for key, value in result.items() if key != "evidence_id"}
    result["evidence_id"] = "EV_" + fingerprint(body)[:24]


def _context_for_call(
    dataset,
    contract,
    root_request,
    evidence_id,
    call_request,
    tool,
    dimension=None,
):
    return trusted_analysis_context(
        dataset.sha256,
        contract,
        root_request,
        {
            evidence_id: trusted_evidence_call(
                contract, call_request, tool, dimension=dimension
            )
        },
    )


def test_build_findings_rejects_numerically_modified_evidence(dataset, contract, request_spec):
    result = Analytics(dataset, contract).compare_periods(request_spec)
    context = _context_for_call(
        dataset, contract, request_spec, result["evidence_id"], request_spec, "compare_periods"
    )
    result["data"]["delta"] = "999999"

    assert build_findings([result], context) == []


def test_build_findings_rejects_fake_evidence_id(dataset, contract, request_spec):
    result = Analytics(dataset, contract).compare_periods(request_spec)
    context = _context_for_call(
        dataset, contract, request_spec, result["evidence_id"], request_spec, "compare_periods"
    )
    result["evidence_id"] = "EV_does_not_exist"

    assert build_findings([result], context) == []


def test_missing_trusted_context_cannot_certify_evidence(dataset, contract, request_spec):
    evidence = Analytics(dataset, contract).compare_periods(request_spec)

    assert build_findings([evidence]) == []


def test_build_findings_rejects_existing_evidence_id_with_wrong_scope(
    dataset, contract, request_spec
):
    result = Analytics(dataset, contract).compare_periods(request_spec)
    wrong_scope = deepcopy(result)
    context = _context_for_call(
        dataset, contract, request_spec, result["evidence_id"], request_spec, "compare_periods"
    )
    wrong_scope["scope"]["filters"] = {"Region": ["North"]}

    assert wrong_scope["evidence_id"] == result["evidence_id"]
    assert build_findings([wrong_scope], context) == []


def test_candidate_builder_does_not_assign_validation(dataset, contract, request_spec):
    evidence = Analytics(dataset, contract).compare_periods(request_spec)

    candidate = build_candidate_findings([evidence])[0]

    assert "validation" not in candidate.model_dump()


def test_numerical_mismatch_fails_against_unchanged_evidence(dataset, contract, request_spec):
    evidence = Analytics(dataset, contract).compare_periods(request_spec)
    candidate = build_candidate_findings([evidence])[0].model_copy(update={"delta": "999999"})
    context = _context_for_call(
        dataset, contract, request_spec, evidence["evidence_id"], request_spec, "compare_periods"
    )

    _, validation = validate_candidate_finding(candidate, [evidence], context)

    assert validation.evidence_linkage == "passed"
    assert validation.scope == "passed"
    assert validation.numerical == "failed"
    assert validation.accepted is False


def test_fake_reference_fails_resolution_against_real_registry(dataset, contract, request_spec):
    evidence = Analytics(dataset, contract).compare_periods(request_spec)
    candidate = build_candidate_findings([evidence])[0].model_copy(
        update={"evidence_id": "EV_does_not_exist"}
    )
    context = _context_for_call(
        dataset, contract, request_spec, evidence["evidence_id"], request_spec, "compare_periods"
    )

    _, validation = validate_candidate_finding(candidate, [evidence], context)

    assert validation.evidence_linkage == "failed"
    assert validation.scope == "not_checked"
    assert validation.numerical == "not_checked"
    assert validation.accepted is False


def test_existing_evidence_with_wrong_candidate_scope_fails_scope_check(
    dataset, contract, request_spec
):
    evidence = Analytics(dataset, contract).compare_periods(request_spec)
    candidate = build_candidate_findings([evidence])[0]
    candidate = candidate.model_copy(
        update={
            "scope": candidate.scope.model_copy(update={"filters": {"Region": ["North"]}})
        }
    )
    context = _context_for_call(
        dataset, contract, request_spec, evidence["evidence_id"], request_spec, "compare_periods"
    )

    _, validation = validate_candidate_finding(candidate, [evidence], context)

    assert validation.evidence_linkage == "passed"
    assert validation.scope == "failed"
    assert validation.numerical == "passed"
    assert validation.accepted is False


def test_structured_text_mismatch_is_not_accepted(dataset, contract, request_spec):
    evidence = Analytics(dataset, contract).compare_periods(request_spec)
    candidate = build_candidate_findings([evidence])[0].model_copy(
        update={"text": "Observed Revenue increased."}
    )
    context = _context_for_call(
        dataset, contract, request_spec, evidence["evidence_id"], request_spec, "compare_periods"
    )

    _, validation = validate_candidate_finding(candidate, [evidence], context)

    assert validation.interpretation == "failed"
    assert validation.accepted is False


def test_known_answer_observation_and_contributions_are_accepted(
    dataset, contract, request_spec
):
    engine = Analytics(dataset, contract)
    evidence = [
        engine.compare_periods(request_spec),
        engine.breakdown_change(request_spec, "Region"),
    ]

    context = trusted_analysis_context(
        dataset.sha256,
        contract,
        request_spec,
        {
            evidence[0]["evidence_id"]: trusted_evidence_call(
                contract, request_spec, "compare_periods"
            ),
            evidence[1]["evidence_id"]: trusted_evidence_call(
                contract, request_spec, "breakdown_change", dimension="Region"
            ),
        },
    )
    records = validate_candidate_findings(build_candidate_findings(evidence), evidence, context)

    assert records
    assert all(record["validation"]["accepted"] for record in records)
    assert all(record["validation"]["numerical"] == "passed" for record in records)
    assert all(record["validation"]["evidence_linkage"] == "passed" for record in records)
    assert all(record["validation"]["scope"] == "passed" for record in records)
    assert all(record["validation"]["interpretation"] == "passed" for record in records)


@pytest.mark.parametrize(
    ("path", "corrupt_display"),
    [
        (("previous", "amount"), "999999"),
        (("current", "amount"), "999999"),
        (("delta",), "999999"),
    ],
)
def test_rehashed_evidence_with_wrong_amount_display_is_rejected(
    dataset, contract, request_spec, path, corrupt_display
):
    evidence = Analytics(dataset, contract).compare_periods(request_spec)
    target = evidence["data"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = corrupt_display
    _rehash_evidence(evidence)
    candidate = build_candidate_findings([evidence])[0]
    context = _context_for_call(
        dataset, contract, request_spec, evidence["evidence_id"], request_spec, "compare_periods"
    )

    _, validation = validate_candidate_finding(candidate, [evidence], context)

    assert validation.evidence_linkage == "passed"
    assert validation.numerical == "failed"
    assert validation.accepted is False


@pytest.mark.parametrize(
    ("field", "value"), [("previous", "999999"), ("current", "999999")]
)
def test_candidate_period_amount_must_match_unchanged_evidence(
    dataset, contract, request_spec, field, value
):
    evidence = Analytics(dataset, contract).compare_periods(request_spec)
    candidate = build_candidate_findings([evidence])[0]
    candidate = candidate.model_copy(
        update={
            field: value,
            "text": (
                f"Observed Revenue changed from "
                f"{value if field == 'previous' else candidate.previous} to "
                f"{value if field == 'current' else candidate.current} VND; "
                f"difference {candidate.delta} VND."
            ),
        }
    )
    context = _context_for_call(
        dataset, contract, request_spec, evidence["evidence_id"], request_spec, "compare_periods"
    )

    _, validation = validate_candidate_finding(candidate, [evidence], context)

    assert validation.interpretation == "passed"
    assert validation.numerical == "failed"
    assert validation.accepted is False


def test_known_answer_amount_displays_match_minor_units(dataset, contract, request_spec):
    evidence = Analytics(dataset, contract).compare_periods(request_spec)
    candidate = build_candidate_findings([evidence])[0]

    assert (
        evidence["data"]["previous"]["amount_minor"],
        evidence["data"]["previous"]["amount"],
        evidence["data"]["current"]["amount_minor"],
        evidence["data"]["current"]["amount"],
        evidence["data"]["delta_minor"],
        evidence["data"]["delta"],
    ) == (1000, "1000", 600, "600", -400, "-400")
    assert (candidate.previous, candidate.current, candidate.delta) == (
        "1000",
        "600",
        "-400",
    )


def test_boolean_minor_units_are_malformed_even_when_rehashed(dataset, contract, request_spec):
    evidence = Analytics(dataset, contract).compare_periods(request_spec)
    evidence["data"]["previous"].update({"amount_minor": True, "amount": "1"})
    evidence["data"].update({"delta_minor": 599, "delta": "599"})
    _rehash_evidence(evidence)
    context = _context_for_call(
        dataset, contract, request_spec, evidence["evidence_id"], request_spec, "compare_periods"
    )

    assert build_findings([evidence], context) == []


def test_scale_two_known_answer_is_accepted_without_analytics_oracle():
    evidence = {
        "schema_version": "1.0",
        "tool_version": "1.0",
        "tool": "compare_periods",
        "dataset_hash": "a" * 64,
        "contract_fingerprint": "b" * 64,
        "scope": {
            "metric_id": "Revenue",
            "previous": {"start": "2026-01-01", "end": "2026-02-01"},
            "current": {"start": "2026-02-01", "end": "2026-03-01"},
            "filters": {},
            "unit": "USD",
            "scale": 2,
        },
        "data": {
            "previous": {
                "amount_minor": 123,
                "amount": "1.23",
                "row_count": 1,
                "valid_count": 1,
                "excluded_null_count": 0,
                "status": "observed",
                "coverage_confirmed": True,
            },
            "current": {
                "amount_minor": 234,
                "amount": "2.34",
                "row_count": 1,
                "valid_count": 1,
                "excluded_null_count": 0,
                "status": "observed",
                "coverage_confirmed": True,
            },
            "delta_minor": 111,
            "delta": "1.11",
        },
        "warnings": ["PERIOD_LENGTHS_DIFFER"],
    }
    _rehash_evidence(evidence)

    root_scope = AnalysisScope.model_validate(evidence["scope"])
    context = TrustedAnalysisContext(
        dataset_hash=evidence["dataset_hash"],
        contract_fingerprint=evidence["contract_fingerprint"],
        root_scope=root_scope,
        coverage=Period(start="2026-01-01", end="2026-03-01"),
        coverage_confirmed=True,
        null_policy="reject",
        evidence_calls={
            evidence["evidence_id"]: TrustedEvidenceCall(
                tool="compare_periods", scope=root_scope
            )
        },
    )
    records = validate_candidate_findings(
        build_candidate_findings([evidence]), [evidence], context
    )

    assert len(records) == 1
    assert records[0]["validation"]["accepted"] is True
    assert (
        records[0]["previous"],
        records[0]["current"],
        records[0]["delta"],
    ) == ("1.23", "2.34", "1.11")


def test_malformed_scope_fails_closed_without_suppressing_valid_finding(
    dataset, contract, request_spec
):
    valid = Analytics(dataset, contract).compare_periods(request_spec)
    malformed = deepcopy(valid)
    malformed["scope"]["unit"] = None
    _rehash_evidence(malformed)

    context = trusted_analysis_context(
        dataset.sha256,
        contract,
        request_spec,
        {
            malformed["evidence_id"]: trusted_evidence_call(
                contract, request_spec, "compare_periods"
            ),
            valid["evidence_id"]: trusted_evidence_call(
                contract, request_spec, "compare_periods"
            ),
        },
    )
    findings = build_findings([malformed, valid], context)

    assert len(findings) == 1
    assert findings[0]["evidence_id"] == valid["evidence_id"]


def test_trusted_context_accepts_valid_narrowed_region_product_evidence(
    dataset, contract, request_spec
):
    child_request = request_spec.model_copy(update={"filters": {"Region": ["North"]}})
    evidence = Analytics(dataset, contract).breakdown_change(child_request, "Product")
    context = _context_for_call(
        dataset,
        contract,
        request_spec,
        evidence["evidence_id"],
        child_request,
        "breakdown_change",
        "Product",
    )

    findings = build_findings([evidence], context)

    assert findings
    assert all(item["validation"]["scope"] == "passed" for item in findings)
    assert all(item["scope"]["filters"] == {"Region": ["North"]} for item in findings)
    assert all(item["scope"]["dimension"] == "Product" for item in findings)


def test_candidate_cannot_change_region_evidence_to_product_extra_filter_scope(
    dataset, contract, request_spec
):
    evidence = Analytics(dataset, contract).breakdown_change(request_spec, "Region")
    candidate = build_candidate_findings([evidence])[0]
    candidate = candidate.model_copy(
        update={
            "scope": candidate.scope.model_copy(
                update={"dimension": "Product", "filters": {"Product": ["A"]}}
            )
        }
    )
    context = _context_for_call(
        dataset,
        contract,
        request_spec,
        evidence["evidence_id"],
        request_spec,
        "breakdown_change",
        "Region",
    )

    _, validation = validate_candidate_finding(candidate, [evidence], context)

    assert validation.scope == "failed"
    assert "FINDING_SCOPE_MISMATCH" in validation.reasons
    assert validation.accepted is False


def test_rehashed_evidence_scope_cannot_replace_trusted_tool_scope(
    dataset, contract, request_spec
):
    evidence = Analytics(dataset, contract).compare_periods(request_spec)
    evidence["scope"]["filters"] = {"Region": ["North"]}
    _rehash_evidence(evidence)
    candidate = build_candidate_findings([evidence])[0]
    context = _context_for_call(
        dataset,
        contract,
        request_spec,
        evidence["evidence_id"],
        request_spec,
        "compare_periods",
    )

    _, validation = validate_candidate_finding(candidate, [evidence], context)

    assert validation.evidence_linkage == "passed"
    assert validation.scope == "failed"
    assert "EVIDENCE_SCOPE_CONTEXT_MISMATCH" in validation.reasons
    assert validation.accepted is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("metric_id", "Profit"),
        ("previous", {"start": "2025-12-01", "end": "2026-01-01"}),
        ("current", {"start": "2026-03-01", "end": "2026-04-01"}),
        ("filters", {"Region": ["North"]}),
        ("unit", "USD"),
        ("scale", 2),
        ("dimension", "Product"),
    ],
)
def test_rehashed_scope_changes_fail_against_trusted_tool_call(
    dataset, contract, request_spec, field, value
):
    evidence = Analytics(dataset, contract).compare_periods(request_spec)
    evidence["scope"][field] = value
    _rehash_evidence(evidence)
    candidate = build_candidate_findings([evidence])[0]
    context = _context_for_call(
        dataset, contract, request_spec, evidence["evidence_id"], request_spec, "compare_periods"
    )

    _, validation = validate_candidate_finding(candidate, [evidence], context)

    assert validation.scope == "failed"
    assert "EVIDENCE_SCOPE_CONTEXT_MISMATCH" in validation.reasons
    assert validation.accepted is False


@pytest.mark.parametrize("field", ["dataset_hash", "contract_fingerprint"])
def test_rehashed_stale_source_context_is_rejected(
    dataset, contract, request_spec, field
):
    evidence = Analytics(dataset, contract).compare_periods(request_spec)
    evidence[field] = "0" * 64
    _rehash_evidence(evidence)
    candidate = build_candidate_findings([evidence])[0]
    context = _context_for_call(
        dataset, contract, request_spec, evidence["evidence_id"], request_spec, "compare_periods"
    )

    _, validation = validate_candidate_finding(candidate, [evidence], context)

    assert validation.scope == "failed"
    assert validation.reasons == [
        "EVIDENCE_DATASET_MISMATCH"
        if field == "dataset_hash"
        else "EVIDENCE_CONTRACT_MISMATCH"
    ]
    assert validation.accepted is False


def test_wrong_tool_cannot_reuse_a_trusted_compare_call(dataset, contract, request_spec):
    evidence = Analytics(dataset, contract).compare_periods(request_spec)
    candidate = build_candidate_findings([evidence])[0]
    evidence["tool"] = "breakdown_change"
    _rehash_evidence(evidence)
    candidate = candidate.model_copy(update={"evidence_id": evidence["evidence_id"]})
    context = _context_for_call(
        dataset, contract, request_spec, evidence["evidence_id"], request_spec, "compare_periods"
    )

    _, validation = validate_candidate_finding(candidate, [evidence], context)

    assert validation.scope == "failed"
    assert "EVIDENCE_TOOL_CONTEXT_MISMATCH" in validation.reasons
    assert validation.accepted is False


def test_unknown_field_reference_is_rejected(dataset, contract, request_spec):
    evidence = Analytics(dataset, contract).compare_periods(request_spec)
    candidate = build_candidate_findings([evidence])[0].model_copy(
        update={"field_refs": ["data.secret"]}
    )
    context = _context_for_call(
        dataset, contract, request_spec, evidence["evidence_id"], request_spec, "compare_periods"
    )

    _, validation = validate_candidate_finding(candidate, [evidence], context)

    assert validation.numerical == "failed"
    assert "FINDING_VALUE_MISMATCH" in validation.reasons
    assert validation.accepted is False


def test_unknown_group_index_is_rejected(dataset, contract, request_spec):
    evidence = Analytics(dataset, contract).breakdown_change(request_spec, "Region")
    candidate = build_candidate_findings([evidence])[0].model_copy(
        update={"group_index": 999}
    )
    context = _context_for_call(
        dataset,
        contract,
        request_spec,
        evidence["evidence_id"],
        request_spec,
        "breakdown_change",
        "Region",
    )

    _, validation = validate_candidate_finding(candidate, [evidence], context)

    assert validation.numerical == "failed"
    assert "EVIDENCE_FIELD_NOT_FOUND" in validation.reasons
    assert validation.accepted is False


def test_duplicate_identical_evidence_deduplicates_but_id_collision_rejects(
    dataset, contract, request_spec
):
    evidence = Analytics(dataset, contract).compare_periods(request_spec)
    context = _context_for_call(
        dataset, contract, request_spec, evidence["evidence_id"], request_spec, "compare_periods"
    )
    candidate = build_candidate_findings([evidence])[0]

    _, identical_validation = validate_candidate_finding(
        candidate, [evidence, deepcopy(evidence)], context
    )
    collision = deepcopy(evidence)
    collision["data"]["delta"] = "999999"
    _, collision_validation = validate_candidate_finding(
        candidate, [evidence, collision], context
    )

    assert identical_validation.accepted is True
    assert collision_validation.evidence_linkage == "failed"
    assert "EVIDENCE_ID_COLLISION" in collision_validation.reasons
    assert collision_validation.accepted is False


def test_rehashed_contribution_percentage_is_checked_against_independent_ratio(
    dataset, contract, request_spec
):
    evidence = Analytics(dataset, contract).breakdown_change(request_spec, "Region")
    south = next(row for row in evidence["data"]["groups"] if row["label"] == "South")
    assert (south["delta_minor"], evidence["data"]["overall"]["delta_minor"]) == (-250, -400)
    assert Decimal("-250") * 100 / Decimal("-400") == Decimal("62.5")
    south["net_contribution_pct"] = "999999"
    _rehash_evidence(evidence)
    candidate = next(
        item for item in build_candidate_findings([evidence]) if item.label == "South"
    )
    context = _context_for_call(
        dataset,
        contract,
        request_spec,
        evidence["evidence_id"],
        request_spec,
        "breakdown_change",
        "Region",
    )

    _, validation = validate_candidate_finding(candidate, [evidence], context)

    assert validation.numerical == "failed"
    assert "CONTRIBUTION_PERCENT_MISMATCH" in validation.reasons
    assert validation.accepted is False


def test_rehashed_wrong_overall_denominator_fails_group_reconciliation(
    dataset, contract, request_spec
):
    evidence = Analytics(dataset, contract).breakdown_change(request_spec, "Region")
    evidence["data"]["overall"]["delta_minor"] = -500
    evidence["data"]["overall"]["delta"] = "-500"
    _rehash_evidence(evidence)
    candidate = next(
        item for item in build_candidate_findings([evidence]) if item.label == "South"
    )
    context = _context_for_call(
        dataset,
        contract,
        request_spec,
        evidence["evidence_id"],
        request_spec,
        "breakdown_change",
        "Region",
    )

    _, validation = validate_candidate_finding(candidate, [evidence], context)

    assert validation.numerical == "failed"
    assert "CONTRIBUTION_RECONCILIATION_FAILED" in validation.reasons
    assert validation.accepted is False


def test_missing_and_duplicated_groups_fail_partition_reconciliation(
    dataset, contract, request_spec
):
    original = Analytics(dataset, contract).breakdown_change(request_spec, "Region")
    missing = deepcopy(original)
    missing["data"]["groups"].pop()
    _rehash_evidence(missing)
    duplicate = deepcopy(original)
    duplicate["data"]["groups"].append(deepcopy(duplicate["data"]["groups"][0]))
    _rehash_evidence(duplicate)

    validations = []
    for evidence in (missing, duplicate):
        candidate = build_candidate_findings([evidence])[0]
        context = _context_for_call(
            dataset,
            contract,
            request_spec,
            evidence["evidence_id"],
            request_spec,
            "breakdown_change",
            "Region",
        )
        _, validation = validate_candidate_finding(candidate, [evidence], context)
        validations.append(validation)

    assert all(item.numerical == "failed" for item in validations)
    assert "CONTRIBUTION_RECONCILIATION_FAILED" in validations[0].reasons
    assert "DUPLICATE_EVIDENCE_GROUP" in validations[1].reasons
    assert all(item.accepted is False for item in validations)


def test_natural_excluded_null_group_keeps_partition_unavailable_even_if_relabelled(
    contract, policy, request_spec
):
    changed = contract.model_copy(deep=True)
    changed.metrics[0].null_policy = "exclude"
    rows = [
        ["1", "O1", "2026-01-05", "C1", "South", "A", "900"],
        ["2", "O2", "2026-01-05", "C2", "North", "A", "100"],
        ["3", "O3", "2026-02-05", "C1", "South", "A", ""],
        ["4", "O4", "2026-02-05", "C2", "North", "A", "200"],
    ]
    source = load_csv_bytes(make_csv(rows), policy)
    evidence = Analytics(source, changed).breakdown_change(request_spec, "Region")
    overall = evidence["data"]["overall"]
    assert (overall["previous"]["amount_minor"], overall["current"]["amount_minor"]) == (
        1000,
        200,
    )
    assert evidence["data"]["numerical_validation"] == "not_checked"

    evidence["data"]["numerical_validation"] = "passed"
    _rehash_evidence(evidence)
    context = _context_for_call(
        source,
        changed,
        request_spec,
        evidence["evidence_id"],
        request_spec,
        "breakdown_change",
        "Region",
    )
    candidates = build_candidate_findings([evidence])
    assert len(candidates) == 1 and candidates[0].label == "North"

    records = validate_candidate_findings(candidates, [evidence], context)

    assert records[0]["validation"]["accepted"] is False
    assert records[0]["validation"]["numerical"] == "not_checked"
    assert "CONTRIBUTION_PARTITION_UNAVAILABLE" in records[0]["validation"]["reasons"]


def test_rehashed_removal_of_zero_delta_group_fails_partition_metadata(
    contract, policy, request_spec
):
    rows = [
        ["1", "O1", "2026-01-05", "C1", "South", "A", "0"],
        ["2", "O2", "2026-01-05", "C2", "North", "A", "100"],
        ["3", "O3", "2026-02-05", "C1", "South", "A", "0"],
        ["4", "O4", "2026-02-05", "C2", "North", "A", "200"],
    ]
    source = load_csv_bytes(make_csv(rows), policy)
    evidence = Analytics(source, contract).breakdown_change(request_spec, "Region")
    south = next(group for group in evidence["data"]["groups"] if group["label"] == "South")
    assert south["delta_minor"] == 0
    evidence["data"]["groups"] = [
        group for group in evidence["data"]["groups"] if group["label"] != "South"
    ]
    _rehash_evidence(evidence)
    candidate = build_candidate_findings([evidence])[0]
    context = _context_for_call(
        source,
        contract,
        request_spec,
        evidence["evidence_id"],
        request_spec,
        "breakdown_change",
        "Region",
    )

    _, validation = validate_candidate_finding(candidate, [evidence], context)

    assert validation.accepted is False
    assert validation.numerical == "failed"
    assert "CONTRIBUTION_PARTITION_METADATA_MISMATCH" in validation.reasons


def test_rehashed_remaining_group_cannot_forge_denominator_over_null_partition(
    contract, policy, request_spec
):
    changed = contract.model_copy(deep=True)
    changed.metrics[0].null_policy = "exclude"
    rows = [
        ["1", "O1", "2026-01-05", "C1", "South", "A", "900"],
        ["2", "O2", "2026-01-05", "C2", "North", "A", "100"],
        ["3", "O3", "2026-02-05", "C1", "South", "A", ""],
        ["4", "O4", "2026-02-05", "C2", "North", "A", "200"],
    ]
    source = load_csv_bytes(make_csv(rows), policy)
    evidence = Analytics(source, changed).breakdown_change(request_spec, "Region")
    overall = evidence["data"]["overall"]
    assert (overall["previous"]["row_count"], overall["current"]["row_count"]) == (2, 2)
    assert (overall["current"]["valid_count"], overall["current"]["excluded_null_count"]) == (
        1,
        1,
    )

    # Remove South, then forge the remaining overall denominator and amounts so that
    # the present North group alone reconciles while overall row/null metadata remains.
    north = next(group for group in evidence["data"]["groups"] if group["label"] == "North")
    evidence["data"]["groups"] = [north]
    overall["previous"]["amount_minor"] = 100
    overall["previous"]["amount"] = "100"
    overall["delta_minor"] = 100
    overall["delta"] = "100"
    north["net_contribution_pct"] = "100"
    evidence["data"]["numerical_validation"] = "passed"
    _rehash_evidence(evidence)
    candidate = build_candidate_findings([evidence])[0]
    context = _context_for_call(
        source,
        changed,
        request_spec,
        evidence["evidence_id"],
        request_spec,
        "breakdown_change",
        "Region",
    )

    _, validation = validate_candidate_finding(candidate, [evidence], context)

    assert validation.accepted is False
    assert validation.numerical == "failed"
    assert "CONTRIBUTION_PARTITION_METADATA_MISMATCH" in validation.reasons


def test_unavailable_group_delta_blocks_all_contribution_findings(
    contract, policy, request_spec
):
    changed = contract.model_copy(deep=True)
    changed.metrics[0].null_policy = "exclude"
    rows = [
        ["1", "O1", "2026-01-05", "C1", "South", "A", "200"],
        ["2", "O2", "2026-01-05", "C2", "North", "A", "100"],
        ["3", "O3", "2026-02-05", "C1", "South", "A", ""],
        ["4", "O4", "2026-02-05", "C2", "North", "A", "200"],
    ]
    incomplete_dataset = load_csv_bytes(make_csv(rows), policy)
    evidence = Analytics(incomplete_dataset, changed).breakdown_change(
        request_spec, "Region"
    )
    assert evidence["data"]["numerical_validation"] == "not_checked"
    assert any(group["delta_minor"] is None for group in evidence["data"]["groups"])
    context = _context_for_call(
        incomplete_dataset,
        changed,
        request_spec,
        evidence["evidence_id"],
        request_spec,
        "breakdown_change",
        "Region",
    )

    records = validate_candidate_findings(
        build_candidate_findings([evidence]), [evidence], context
    )

    assert records
    assert all(record["validation"]["accepted"] is False for record in records)
    assert all(
        record["validation"]["numerical"] == "not_checked"
        and "CONTRIBUTION_PARTITION_UNAVAILABLE" in record["validation"]["reasons"]
        for record in records
    )


def test_rehashed_overall_denominator_cannot_support_claim_with_unavailable_group(
    contract, policy, request_spec
):
    changed = contract.model_copy(deep=True)
    changed.metrics[0].null_policy = "exclude"
    rows = [
        ["1", "O1", "2026-01-05", "C1", "South", "A", "900"],
        ["2", "O2", "2026-01-05", "C2", "North", "A", "100"],
        ["3", "O3", "2026-02-05", "C1", "South", "A", ""],
        ["4", "O4", "2026-02-05", "C2", "North", "A", "200"],
    ]
    incomplete_dataset = load_csv_bytes(make_csv(rows), policy)
    evidence = Analytics(incomplete_dataset, changed).breakdown_change(
        request_spec, "Region"
    )
    north = next(row for row in evidence["data"]["groups"] if row["label"] == "North")
    assert north["delta_minor"] == 100
    assert evidence["data"]["numerical_validation"] == "not_checked"

    # Rehash a plausible but unsupported overall denominator and matching North ratio.
    overall = evidence["data"]["overall"]
    overall["current"]["amount_minor"] = 500
    overall["current"]["amount"] = "500"
    overall["delta_minor"] = -500
    overall["delta"] = "-500"
    north["net_contribution_pct"] = "-20"
    _rehash_evidence(evidence)
    context = _context_for_call(
        incomplete_dataset,
        changed,
        request_spec,
        evidence["evidence_id"],
        request_spec,
        "breakdown_change",
        "Region",
    )

    candidates = build_candidate_findings([evidence])
    assert len(candidates) == 1 and candidates[0].label == "North"
    records = validate_candidate_findings(candidates, [evidence], context)

    assert records[0]["validation"]["accepted"] is False
    assert records[0]["validation"]["numerical"] == "not_checked"
    assert "CONTRIBUTION_PARTITION_UNAVAILABLE" in records[0]["validation"]["reasons"]


def test_unbounded_contribution_percent_fails_closed_in_public_pipeline(
    dataset, contract, request_spec
):
    engine = Analytics(dataset, contract)
    comparison = engine.compare_periods(request_spec)
    evidence = engine.breakdown_change(request_spec, "Region")
    evidence["data"]["groups"][0]["net_contribution_pct"] = "1e9999999"
    _rehash_evidence(evidence)
    context = trusted_analysis_context(
        dataset.sha256,
        contract,
        request_spec,
        {
            comparison["evidence_id"]: trusted_evidence_call(
                contract, request_spec, "compare_periods"
            ),
            evidence["evidence_id"]: trusted_evidence_call(
                contract, request_spec, "breakdown_change", dimension="Region"
            ),
        },
    )

    corrupted_candidate = build_candidate_findings([evidence])[0]
    _, validation = validate_candidate_finding(corrupted_candidate, [evidence], context)
    findings = build_findings([comparison, evidence], context)

    assert validation.numerical == "failed"
    assert "CONTRIBUTION_PERCENT_MISMATCH" in validation.reasons
    assert len(findings) == 1
    assert findings[0]["claim_type"] == "observation"
    assert findings[0]["validation"]["accepted"] is True


def test_zero_net_keeps_percentages_unavailable_and_rejects_fabricated_ratio(
    contract, policy, request_spec
):
    rows = [
        ["1", "O1", "2026-01-05", "C1", "South", "A", "200"],
        ["2", "O2", "2026-01-05", "C2", "North", "A", "100"],
        ["3", "O3", "2026-02-05", "C1", "South", "A", "80"],
        ["4", "O4", "2026-02-05", "C2", "North", "A", "220"],
    ]
    zero_net_dataset = load_csv_bytes(make_csv(rows), policy)
    evidence = Analytics(zero_net_dataset, contract).breakdown_change(request_spec, "Region")
    assert evidence["data"]["overall"]["delta_minor"] == 0
    assert all(row["net_contribution_pct"] is None for row in evidence["data"]["groups"])
    context = _context_for_call(
        zero_net_dataset,
        contract,
        request_spec,
        evidence["evidence_id"],
        request_spec,
        "breakdown_change",
        "Region",
    )
    records = validate_candidate_findings(
        build_candidate_findings([evidence]), [evidence], context
    )
    assert records
    assert all(record["validation"]["accepted"] for record in records)

    evidence["data"]["groups"][0]["net_contribution_pct"] = "100"
    _rehash_evidence(evidence)
    context = _context_for_call(
        zero_net_dataset,
        contract,
        request_spec,
        evidence["evidence_id"],
        request_spec,
        "breakdown_change",
        "Region",
    )
    candidate = build_candidate_findings([evidence])[0]
    _, validation = validate_candidate_finding(candidate, [evidence], context)
    assert validation.numerical == "failed"
    assert "CONTRIBUTION_PERCENT_MISMATCH" in validation.reasons
    assert validation.accepted is False


def test_rehashed_all_null_period_cannot_be_promoted_to_zero(
    contract, policy, request_spec
):
    changed = contract.model_copy(deep=True)
    changed.metrics[0].null_policy = "exclude"
    rows = [
        ["1", "O1", "2026-01-05", "C1", "South", "A", "100"],
        ["2", "O2", "2026-02-05", "C2", "North", "A", ""],
    ]
    null_dataset = load_csv_bytes(make_csv(rows), policy)
    evidence = Analytics(null_dataset, changed).compare_periods(request_spec)
    assert evidence["data"]["current"]["status"] == "no_valid_values"
    assert evidence["data"]["current"]["amount_minor"] is None
    assert evidence["data"]["delta_minor"] is None

    # Rehashing proves integrity alone cannot turn an all-null period into an observed zero.
    evidence["data"]["current"]["amount_minor"] = 0
    evidence["data"]["current"]["amount"] = "0"
    evidence["data"]["delta_minor"] = -100
    evidence["data"]["delta"] = "-100"
    _rehash_evidence(evidence)
    candidate = build_candidate_findings([evidence])[0]
    context = _context_for_call(
        null_dataset,
        changed,
        request_spec,
        evidence["evidence_id"],
        request_spec,
        "compare_periods",
    )

    _, validation = validate_candidate_finding(candidate, [evidence], context)

    assert validation.numerical == "failed"
    assert "EVIDENCE_PERIOD_STATE_INVALID" in validation.reasons
    assert validation.accepted is False


def test_rehashed_all_null_segment_cannot_be_promoted_to_zero(
    contract, policy, request_spec
):
    changed = contract.model_copy(deep=True)
    changed.metrics[0].null_policy = "exclude"
    rows = [
        ["1", "O1", "2026-01-05", "C1", "South", "A", "200"],
        ["2", "O2", "2026-01-05", "C2", "North", "A", "100"],
        ["3", "O3", "2026-02-05", "C1", "South", "A", ""],
        ["4", "O4", "2026-02-05", "C2", "North", "A", "200"],
    ]
    null_dataset = load_csv_bytes(make_csv(rows), policy)
    evidence = Analytics(null_dataset, changed).breakdown_change(request_spec, "Region")
    south = next(row for row in evidence["data"]["groups"] if row["label"] == "South")
    assert south["current_minor"] is None
    assert south["delta_minor"] is None

    # Current group is all null. Forged zero leaves the aggregate sum unchanged, so a
    # group reconciliation alone cannot identify the lost/null group state.
    south["current_minor"] = 0
    south["current"] = "0"
    south["delta_minor"] = -200
    south["delta"] = "-200"
    south["net_contribution_pct"] = "200"
    _rehash_evidence(evidence)
    candidate = next(
        item for item in build_candidate_findings([evidence]) if item.label == "South"
    )
    context = _context_for_call(
        null_dataset,
        changed,
        request_spec,
        evidence["evidence_id"],
        request_spec,
        "breakdown_change",
        "Region",
    )

    _, validation = validate_candidate_finding(candidate, [evidence], context)

    assert validation.numerical == "failed"
    assert "EVIDENCE_PERIOD_STATE_INVALID" in validation.reasons
    assert validation.accepted is False


def test_covered_empty_period_is_known_zero_and_accepts_known_answer(
    contract, policy, request_spec
):
    rows = [["1", "O1", "2026-01-05", "C1", "South", "A", "100"]]
    one_period_dataset = load_csv_bytes(make_csv(rows), policy)
    evidence = Analytics(one_period_dataset, contract).compare_periods(request_spec)
    current = evidence["data"]["current"]
    assert current["status"] == "known_zero"
    assert current["row_count"] == current["valid_count"] == 0
    assert current["amount_minor"] == 0
    context = _context_for_call(
        one_period_dataset,
        contract,
        request_spec,
        evidence["evidence_id"],
        request_spec,
        "compare_periods",
    )

    records = validate_candidate_findings(
        build_candidate_findings([evidence]), [evidence], context
    )

    assert len(records) == 1
    assert records[0]["validation"]["accepted"] is True
    assert records[0]["current_minor"] == 0


def test_unknown_coverage_keeps_observed_period_limited_and_period_specific(
    dataset, contract, request_spec
):
    extended_request = AnalysisRequest.model_validate(
        request_spec.model_dump(mode="json")
        | {"current": {"start": "2026-02-01", "end": "2026-04-01"}}
    )
    evidence = Analytics(dataset, contract).compare_periods(extended_request)
    assert evidence["data"]["previous"]["coverage_confirmed"] is True
    assert evidence["data"]["current"]["coverage_confirmed"] is False
    assert evidence["data"]["current"]["status"] == "observed"
    assert evidence["warnings"] == ["COVERAGE_UNKNOWN", "PERIOD_LENGTHS_DIFFER"]
    context = _context_for_call(
        dataset,
        contract,
        extended_request,
        evidence["evidence_id"],
        extended_request,
        "compare_periods",
    )
    candidate = build_candidate_findings([evidence])[0]

    _, accepted_validation = validate_candidate_finding(candidate, [evidence], context)
    _, dropped_limitation_validation = validate_candidate_finding(
        candidate.model_copy(update={"limitations": []}), [evidence], context
    )

    assert accepted_validation.accepted is True
    assert candidate.limitations == ["COVERAGE_UNKNOWN", "PERIOD_LENGTHS_DIFFER"]
    assert dropped_limitation_validation.numerical == "failed"
    assert "FINDING_LIMITATIONS_MISMATCH" in dropped_limitation_validation.reasons
    assert dropped_limitation_validation.accepted is False
