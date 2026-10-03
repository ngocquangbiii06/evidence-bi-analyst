"""Bounded synthetic performance probe with an independently accumulated expected total."""

import argparse
import csv
import io
import json
import platform
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bi_analyst.analytics import Analytics  # noqa: E402
from bi_analyst.contracts import AnalysisRequest, BusinessContract, DataPolicy  # noqa: E402
from bi_analyst.data import load_csv_bytes  # noqa: E402


def benchmark(count=200_000):
    root = Path(__file__).resolve().parents[1]
    contract = BusinessContract.model_validate_json(
        (root / "examples/business_config.json").read_text()
    )
    request = AnalysisRequest.model_validate_json((root / "examples/question.json").read_text())
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(
        ["LineID", "OrderID", "OrderDate", "CustomerID", "Region", "Product", "Revenue"]
    )
    expected = [0, 0]
    for i in range(count):
        month = 1 + i % 2
        value = 100 + (i * 17) % 900
        expected[month - 1] += value
        writer.writerow(
            [
                f"L{i:08}",
                f"O{i:08}",
                f"2026-{month:02}-15",
                f"C{i % 1000}",
                f"Region{i % 7}",
                f"Product{i % 11}",
                value,
            ]
        )
    raw = stream.getvalue().encode()
    start = time.perf_counter()
    data = load_csv_bytes(raw, DataPolicy())
    loaded = time.perf_counter()
    engine = Analytics(data, contract)
    profiled = time.perf_counter()
    result = engine.compare_periods(request)
    compared = time.perf_counter()
    breakdown = engine.breakdown_change(request, "Region")
    completed = time.perf_counter()
    assert result["data"]["previous"]["amount_minor"] == expected[0]
    assert result["data"]["current"]["amount_minor"] == expected[1]
    assert breakdown["data"]["numerical_validation"] == "passed"
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "rows": count,
        "input_bytes": len(raw),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "seconds": {
            "load": loaded - start,
            "profile": profiled - loaded,
            "compare": compared - profiled,
            "breakdown": completed - compared,
            "total": completed - start,
        },
        "process_peak_rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
        "expected_totals_minor": expected,
        "independent_totals_match": True,
        "groups_reconciled": True,
        "note": "One synthetic benchmark run; not a latency SLA or p95 measurement.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=200_000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = benchmark(args.rows)
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")
    print(text)
