"""Local command line; errors never print untrusted input values."""

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .contracts import AnalysisRequest, BusinessContract, DataPolicy, ParserConfig
from .errors import BIError
from .store import RunStore
from .workflow import analyze_deterministic, ingest_run


def read_config(path, model):
    with Path(path).open("rb") as stream:
        content = stream.read(65_537)
    if len(content) > 65_536:
        raise BIError("CONFIG_LIMIT", "Configuration exceeds 64 KiB.")
    return model.model_validate_json(content)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="bi-analyst")
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument(
        "--owner",
        default="local",
        help="Trusted local OS operator: select a saved session owner. Never used by model tools or HTTP input.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    suggest = commands.add_parser("suggest-semantics")
    suggest.add_argument("--input", required=True, type=Path)
    suggest.add_argument("--delimiter", default=",", choices=[",", ";", "\t"])
    suggest.add_argument("--policy", type=Path)
    suggest.add_argument("--model")
    profile = commands.add_parser("profile")
    profile.add_argument("--input", required=True, type=Path)
    profile.add_argument("--contract", required=True, type=Path)
    profile.add_argument("--policy", required=True, type=Path)
    profile.add_argument("--delimiter", default=",", choices=[",", ";", "\t"])
    analyze = commands.add_parser("analyze")
    analyze.add_argument("run_id")
    analyze.add_argument("--request", required=True, type=Path)
    agent = commands.add_parser("agent")
    agent.add_argument("run_id")
    agent.add_argument("--request", required=True, type=Path)
    agent.add_argument("--model", required=True)
    agent.add_argument("--resume", action="store_true")
    export = commands.add_parser("export-powerbi")
    export.add_argument("run_id")
    export.add_argument("--request", required=True, type=Path)
    export.add_argument("--output", required=True, type=Path)
    runs = commands.add_parser("runs").add_subparsers(dest="action", required=True)
    for action in ["show", "delete", "save"]:
        runs.add_parser(action).add_argument("run_id")
    runs.add_parser("list").add_argument(
        "--all-sessions",
        action="store_true",
        help="List local session metadata, including saved browser sessions.",
    )
    runs.add_parser("cleanup-expired")
    args = parser.parse_args(argv)
    try:
        store = RunStore(args.runtime_root, owner=args.owner)
        if args.command == "suggest-semantics":
            from .data import load_csv
            from .semantics import propose_semantics

            policy = read_config(args.policy, DataPolicy) if args.policy else DataPolicy()
            dataset = load_csv(args.input, policy, ParserConfig(delimiter=args.delimiter))
            if args.model:
                from .provider import OpenAIAdapter
                from .stages import review_semantics

                result = review_semantics(
                    dataset,
                    policy,
                    store,
                    OpenAIAdapter(args.model, purpose="semantic_review"),
                    policy_path=args.policy,
                )
            else:
                result = propose_semantics(dataset)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "profile":
            contract = read_config(args.contract, BusinessContract)
            policy = read_config(args.policy, DataPolicy)
            run_id = ingest_run(
                args.input,
                contract,
                policy,
                store,
                ParserConfig(delimiter=args.delimiter),
                policy_path=args.policy,
            )
            manifest = store.manifest(run_id)
            print(
                json.dumps(
                    {
                        "run_id": run_id,
                        "status": manifest["status"],
                        "runtime_root": str(store.root),
                    }
                )
            )
            return 0 if manifest["status"] == "READY" else 2
        if args.command == "agent":
            from .provider import OpenAIAdapter
            from .runtime import AgentRunner

            report = AgentRunner(store, OpenAIAdapter(args.model)).run(
                args.run_id, read_config(args.request, AnalysisRequest), resume=args.resume
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["status"] == "COMPLETED" else 2
        if args.command == "export-powerbi":
            from .bi import export_powerbi

            result = export_powerbi(
                args.run_id,
                store,
                args.output,
                read_config(args.request, AnalysisRequest),
            )
            print(json.dumps(result))
            return 0
        if args.command == "analyze":
            report = analyze_deterministic(
                args.run_id, store, read_config(args.request, AnalysisRequest)
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.action == "show":
            print(json.dumps(store.manifest(args.run_id, allow_expired=True), indent=2))
        elif args.action == "list":
            from .store import local_session_manifests

            manifests = (
                [m for _, m in local_session_manifests(store.root)]
                if args.all_sessions
                else store.list_runs()
            )
            print(json.dumps(manifests, indent=2))
        elif args.action == "save":
            store.update(args.run_id, saved=True)
            print(json.dumps({"saved": args.run_id, "retention": "until explicitly deleted"}))
        elif args.action == "delete":
            store.delete(args.run_id)
            print(json.dumps({"deleted_app_run": args.run_id, "source_file_deleted": False}))
        elif args.action == "cleanup-expired":
            print(json.dumps({"deleted": store.cleanup_expired()}))
        return 0
    except BIError as error:
        print(json.dumps({"error": error.as_dict()}), file=sys.stderr)
        return 2
    except (ValidationError, ValueError):
        print(
            '{"error":{"code":"INVALID_CONFIG","message":"Configuration is invalid or incompatible."}}',
            file=sys.stderr,
        )
        return 2
    except OSError:
        print(
            '{"error":{"code":"IO_ERROR","message":"Local file operation failed."}}',
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
