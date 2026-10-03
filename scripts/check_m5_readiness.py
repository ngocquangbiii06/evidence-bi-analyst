"""Run only the offline M5 readiness checks; this command cannot start live runs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from bi_analyst.errors import BIError  # noqa: E402
from bi_analyst.live_eval_readiness import run_m5_readiness  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify frozen M5 inputs and run a local deterministic baseline only."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("examples/evaluation/live_config.example.json"),
        help="Non-secret readiness config JSON.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Fresh output directory under deliverables/verification.",
    )
    args = parser.parse_args(argv)
    config_path = args.config if args.config.is_absolute() else PROJECT_ROOT / args.config
    try:
        report = run_m5_readiness(PROJECT_ROOT, config_path, args.output_dir)
    except BIError as error:
        print(json.dumps({"status": "failed", "error_code": error.code}, indent=2))
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["offline_readiness"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
