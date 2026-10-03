"""Build the seeded T15 business-case project without replacing an existing export."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from validate_powerbi import (  # noqa: E402
    compare_powerbi_projects,  # noqa: F401
    compare_powerbi_projects_exact,  # noqa: F401
    compare_powerbi_projects_refresh,
    validate_project,
    validate_references,
)

from bi_analyst.bi import export_powerbi  # noqa: E402
from bi_analyst.contracts import AnalysisRequest, BusinessContract, DataPolicy  # noqa: E402
from bi_analyst.store import RunStore  # noqa: E402
from bi_analyst.workflow import analyze_deterministic, ingest_run  # noqa: E402

GENERATOR_VERSION = "dashboard-refresh-r3"
DEFAULT_SEED = 20260923
CSV_FIELDS = ["LineID", "OrderID", "OrderDate", "CustomerID", "Region", "Product", "Revenue"]
PREVIOUS_START = "2026-01-01"
PREVIOUS_END = "2026-02-01"
CURRENT_START = "2026-02-01"
CURRENT_END = "2026-03-01"
REGIONS = ("North", "South", "West")
PRODUCTS = ("Anchor", "Growth", "Stable")
DELTA_BY_INTERSECTION = {
    ("North", "Anchor"): 120_000,
    ("North", "Growth"): 5_000,
    ("North", "Stable"): -3_000,
    ("South", "Anchor"): -25_000,
    ("South", "Growth"): -12_000,
    ("South", "Stable"): -5_000,
    ("West", "Anchor"): -15_000,
    ("West", "Growth"): -8_000,
    ("West", "Stable"): 3_000,
}
GROWTH_RATIO_TOLERANCE = 1e-12
DEFAULT_OUTPUT = Path(tempfile.gettempdir()) / "evidence-bi-demo"
LAYOUT_MANIFEST = ROOT / "docs/design/dashboard_refresh_layout_r3.json"


def generate_demo_rows(seed: int = DEFAULT_SEED) -> list[dict[str, str]]:
    """Return the versioned 18-row fixture; only seeded baselines vary by seed."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an integer")
    rng = random.Random(seed)
    rows = []
    for region in REGIONS:
        for product in PRODUCTS:
            previous = 100_000 + rng.randint(0, 10_000)
            for period, date_text, amount in (
                ("JAN", "2026-01-15", previous),
                ("FEB", "2026-02-15", previous + DELTA_BY_INTERSECTION[(region, product)]),
            ):
                line_id = f"{region[:1]}{product[:1]}-{period}"
                rows.append(
                    {
                        "LineID": line_id,
                        "OrderID": "O-" + line_id,
                        "OrderDate": date_text,
                        "CustomerID": "C-" + line_id,
                        "Region": region,
                        "Product": product,
                        "Revenue": str(amount),
                    }
                )
    return rows


def serialize_demo_csv(rows: list[dict[str, str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _row_matches(row: dict[str, str], context: dict) -> bool:
    if context.get("region") is not None and row["Region"] != context["region"]:
        return False
    if context.get("product") is not None and row["Product"] != context["product"]:
        return False
    if context.get("date") is not None and row["OrderDate"] != context["date"]:
        return False
    return True


def _independent_amount(rows: list[dict[str, str]], context: dict, start=None, end=None):
    """Hand-sum source CSV rows; this deliberately does not call Analytics/tools."""
    total = 0
    matched = 0
    valid = 0
    for row in rows:
        if not _row_matches(row, context):
            continue
        if start is not None and not (start <= row["OrderDate"] < end):
            continue
        matched += 1
        amount = row["Revenue"].strip()
        if amount:
            total += int(amount)
            valid += 1
    return (total if valid else None), matched, valid


def independent_oracle(rows: list[dict[str, str]]) -> dict:
    """Create DAX reconciliation cases from raw rows using independent integer sums."""
    contexts = [
        ("root", {}, ""),
        (
            "region_north",
            {"region": "North"},
            "TREATAS({\"North\"}, 'DimRegion'[Region])",
        ),
        (
            "product_anchor",
            {"product": "Anchor"},
            "TREATAS({\"Anchor\"}, 'DimProduct'[Product])",
        ),
        (
            "intersection_north_anchor",
            {"region": "North", "product": "Anchor"},
            "TREATAS({\"North\"}, 'DimRegion'[Region]), TREATAS({\"Anchor\"}, 'DimProduct'[Product])",
        ),
        (
            "date_january",
            {"date": "2026-01-15"},
            "TREATAS({DATE(2026, 1, 15)}, 'DimDate'[Date])",
        ),
        (
            "date_no_rows",
            {"date": "2026-03-15"},
            "TREATAS({DATE(2026, 3, 15)}, 'DimDate'[Date])",
        ),
        (
            "no_region_rows",
            {"region": "Atlantis"},
            "TREATAS({\"Atlantis\"}, 'DimRegion'[Region])",
        ),
    ]
    cases = []
    for case_id, context, dax_filter in contexts:
        base, _, _ = _independent_amount(rows, context)
        # The report's fixed-period measures remove DimDate filters while keeping
        # Region/Product filters; only the base measure uses the direct date context.
        comparison_context = {key: value for key, value in context.items() if key != "date"}
        previous, previous_rows, previous_valid = _independent_amount(
            rows, comparison_context, PREVIOUS_START, PREVIOUS_END
        )
        current, current_rows, current_valid = _independent_amount(
            rows, comparison_context, CURRENT_START, CURRENT_END
        )
        # Contract coverage is confirmed. An absent group is therefore known zero;
        # rows present with all-null amounts remain blank.
        if previous_rows == 0:
            previous = 0
        elif previous_valid == 0:
            previous = None
        if current_rows == 0:
            current = 0
        elif current_valid == 0:
            current = None
        change = None if previous is None or current is None else current - previous
        growth = change / previous if change is not None and previous > 0 else None
        cases.append(
            {
                "id": case_id,
                "filter": dax_filter,
                "expected": {
                    "Base": base,
                    "Previous": previous,
                    "Current": current,
                    "Change": change,
                    "Growth": growth,
                },
            }
        )
    return {
        "schema_version": "1.0",
        "source": "Independent integer sums over the generated CSV; no Analytics/tool call.",
        "generator_version": GENERATOR_VERSION,
        "seed": None,
        "metric_tolerance": 0,
        "growth_ratio_tolerance": GROWTH_RATIO_TOLERANCE,
        "cases": cases,
    }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tree_sha256(root: Path) -> str:
    records = []
    for path in sorted(
        (p for p in root.rglob("*") if p.is_file()),
        key=lambda p: p.relative_to(root).as_posix().casefold(),
    ):
        records.append(
            f"{_sha256(path.read_bytes())}  {path.relative_to(root).as_posix()}"
        )
    return _sha256(("\n".join(records) + "\n").encode())


def current_tree_manifest(current: Path) -> str:
    records = []
    for path in sorted(
        (p for p in current.rglob("*") if p.is_file()),
        key=lambda p: p.relative_to(current).as_posix().casefold(),
    ):
        relative = path.relative_to(current).as_posix()
        records.append(f"{_sha256(path.read_bytes())}  {relative}")
    return "\n".join(records) + "\n"


def _write_json(path: Path, payload: dict) -> bytes:
    content = (json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    path.write_bytes(content)
    return content


def _same_oracle_and_scenario(rows: list[dict[str, str]], oracle: dict) -> None:
    by_id = {case["id"]: case["expected"] for case in oracle["cases"]}
    root = by_id["root"]
    assert root["Current"] - root["Previous"] == 60_000
    assert root["Growth"] is not None
    assert by_id["region_north"]["Change"] == 122_000
    assert by_id["product_anchor"]["Change"] == 80_000
    intersection = by_id["intersection_north_anchor"]["Change"]
    assert intersection == 120_000
    assert intersection / root["Change"] == 2
    assert sum(int(row["Revenue"]) for row in rows if row["OrderDate"] == CURRENT_START[:7] + "-15") > 0
    assert by_id["date_no_rows"]["Base"] is None
    assert by_id["no_region_rows"]["Base"] is None
    assert by_id["no_region_rows"]["Previous"] == by_id["no_region_rows"]["Current"] == 0


def build(
    output: Path,
    seed: int = DEFAULT_SEED,
    *,
    baseline: Path | None = None,
    verification_output: Path | None = None,
) -> dict:
    output = output.resolve()
    baseline = (baseline or ROOT / "deliverables/PowerBI_Demo_Candidate").resolve()
    current = (ROOT / "deliverables/PowerBI_Demo_Current").resolve()
    if not baseline.is_dir():
        raise FileNotFoundError(f"tracked Power BI baseline does not exist: {baseline}")
    for protected in (baseline, current):
        if output == protected or output in protected.parents or protected in output.parents:
            raise ValueError(
                "candidate output must be a separate sibling tree from the tracked baseline and "
                "PowerBI_Demo_Current"
            )
    if output.exists():
        raise FileExistsError(f"candidate output already exists: {output}")

    before_manifest = current_tree_manifest(baseline)
    before_manifest_sha256 = _sha256(before_manifest.encode())
    verification_path = (
        verification_output.resolve()
        if verification_output is not None
        else output.with_name(output.name + "-verification.json")
    )
    for protected in (baseline, current, output):
        if (
            verification_path == protected
            or verification_path in protected.parents
            or protected in verification_path.parents
        ):
            raise ValueError("verification output must not overwrite a protected Power BI tree")
    if verification_path.exists():
        raise FileExistsError(f"verification output already exists: {verification_path}")

    rows = generate_demo_rows(seed)
    csv_bytes = serialize_demo_csv(rows)
    oracle = independent_oracle(rows)
    oracle["seed"] = seed
    _same_oracle_and_scenario(rows, oracle)
    with tempfile.TemporaryDirectory(prefix="pbi-t15-build-") as temp_dir:
        source = Path(temp_dir) / "demo_sales.csv"
        source.write_bytes(csv_bytes)
        store = RunStore(Path(temp_dir) / "runtime")
        contract = BusinessContract.model_validate_json(
            (ROOT / "examples/business_config.json").read_text(encoding="utf-8")
        )
        request = AnalysisRequest.model_validate_json(
            (ROOT / "examples/question.json").read_text(encoding="utf-8")
        )
        request = request.model_copy(
            update={
                "question": "How did revenue change between January and February, and which region and product movements offset each other?"
            }
        )
        policy = DataPolicy(dataset_class="synthetic")
        run_id = ingest_run(source, contract, policy, store)
        report = analyze_deterministic(run_id, store, request)
        exported = export_powerbi(run_id, store, output, request)

    oracle_bytes = _write_json(output / "verification_cases.json", oracle)
    (output / "demo_sales.csv").write_bytes(csv_bytes)
    demo_manifest = {
        "schema_version": "1.0",
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "row_count": len(rows),
        "csv_schema": CSV_FIELDS,
        "csv_sha256": _sha256(csv_bytes),
        "oracle_sha256": _sha256(oracle_bytes),
        "region_product_deltas_minor": {
            f"{region}/{product}": DELTA_BY_INTERSECTION[(region, product)]
            for region in REGIONS
            for product in PRODUCTS
        },
    }
    _write_json(output / "demo_dataset_manifest.json", demo_manifest)
    exported_evidence = json.loads((output / "evidence.json").read_text(encoding="utf-8"))
    _write_json(
        output / "business_case_summary.json",
        {
            "schema_version": "1.0",
            "analysis_artifact_fingerprint": exported_evidence[
                "validated_analysis_fingerprint"
            ],
            "accepted_quantitative_results": [
                {
                    "finding_id": record["candidate"]["finding_id"],
                    "claim_type": record["candidate"]["claim_type"],
                    "text": record["candidate"]["text"],
                    "evidence_id": record["candidate"]["evidence_id"],
                }
                for record in exported_evidence["findings"]
            ],
            "unknowns": list(exported_evidence["limitations"]),
            "next_investigation_step": (
                "Collect promotion, availability, and fulfillment observations at the same "
                "Region/Product/date scope, then test any proposed driver against that evidence."
            ),
            "causal_claim": "not_established",
        },
    )

    schema_report = validate_project(output)
    reference_report = validate_references(output)
    layout_report = compare_powerbi_projects_refresh(
        baseline,
        output,
        layout_manifest=LAYOUT_MANIFEST,
    )
    if schema_report["failures"] or reference_report["failures"] or layout_report["failures"]:
        raise RuntimeError(
            "candidate static verification failed: "
            + json.dumps(
                {
                    "schema": schema_report["failures"],
                    "references": reference_report["failures"],
                    "layout": layout_report["failures"],
                },
                indent=2,
            )
        )

    after_manifest = current_tree_manifest(baseline)
    if after_manifest != before_manifest:
        raise RuntimeError("tracked Power BI baseline changed while building the candidate")
    candidate_evidence = {
        "schema_version": "1.0",
        "candidate": str(output),
        "seed": seed,
        "generator_version": GENERATOR_VERSION,
        "run_id": run_id,
        "analysis_status": report.get("status"),
        "dataset_sha256": demo_manifest["csv_sha256"],
        "model_sha256": _sha256((output / "EvidenceBI.SemanticModel/model.bim").read_bytes()),
        "report_tree_sha256": _tree_sha256(output / "EvidenceBI.Report"),
        "oracle_sha256": demo_manifest["oracle_sha256"],
        "baseline": str(baseline),
        "baseline_manifest_sha256": before_manifest_sha256,
        "baseline_unchanged": True,
        "layout_manifest": str(LAYOUT_MANIFEST),
        "layout_manifest_sha256": _sha256(LAYOUT_MANIFEST.read_bytes()),
        "schema": "passed",
        "model_dax_report_references": "passed",
        "pbir_refresh_allowlist": "passed",
        "execution": "not_checked",
        "reconciliation": "not_checked",
        "interactions": "not_checked",
        "rendering": "not_checked",
        "desktop_version": None,
    }
    verification_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(verification_path, candidate_evidence)
    return {
        **exported,
        "run_id": run_id,
        "analysis_status": report.get("status"),
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "dataset_sha256": demo_manifest["csv_sha256"],
        "oracle_sha256": demo_manifest["oracle_sha256"],
        "verification": "static schema, references, and dashboard-refresh allowlist passed",
        "baseline": str(baseline),
        "verification_output": str(verification_path),
        "execution": "not_checked",
        "rendering": "not_checked",
    }


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT
    )
    parser.add_argument(
        "--baseline", type=Path, default=ROOT / "deliverables/PowerBI_Demo_Candidate"
    )
    parser.add_argument("--verification-output", type=Path)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    return parser


if __name__ == "__main__":
    parser = build_argument_parser()
    args = parser.parse_args()
    print(
        json.dumps(
            build(
                args.output,
                seed=args.seed,
                baseline=args.baseline,
                verification_output=args.verification_output,
            ),
            indent=2,
        )
    )
