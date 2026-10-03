"""Execute one explicitly authorized M5 smoke or one frozen acceptance batch."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from bi_analyst.errors import BIError  # noqa: E402
from bi_analyst.live_evaluation import preflight_m5_live, run_m5_live  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded M5 synthetic live evaluation")
    parser.add_argument("phase", choices=("smoke", "batch"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--execute-live", action="store_true")
    parser.add_argument(
        "--prompt-key", action="store_true",
        help="Read the API key invisibly for this process when OPENAI_API_KEY is unset.",
    )
    args = parser.parse_args(argv)
    config_path = args.config if args.config.is_absolute() else PROJECT_ROOT / args.config
    if not args.execute_live:
        print(json.dumps({"status": "blocked_live", "reason": "execute_live_flag_missing"}))
        return 2
    try:
        gate = preflight_m5_live(PROJECT_ROOT, config_path, phase=args.phase)
        if gate["live_readiness"] != "ready_for_t18_preflight":
            print(json.dumps({
                "status": "blocked_live",
                "reasons": gate["blocked_live_reasons"],
            }))
            return 2
        key = os.getenv("OPENAI_API_KEY")
        if not key and args.prompt_key:
            key = getpass.getpass("OpenAI API key (input hidden): ")
        result = run_m5_live(
            PROJECT_ROOT, config_path, phase=args.phase, execute_live=True, key=key
        )
    except BIError as error:
        print(json.dumps({"status": "failed", "error_code": error.code}))
        return 2
    summary = {
        "phase": args.phase,
        "status": result.get("status", result.get("grade", {}).get("overall_status")),
        "output_dir": gate["output_paths"]["live_output_dir"],
        "reserved_usd": result["reserved_usd"],
    }
    print(json.dumps(summary))
    return 0 if summary["status"] in {"passed", "pass"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
