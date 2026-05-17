from __future__ import annotations

import argparse
import json
from pathlib import Path

from cfd_agent.core.models import load_simulation_task
from cfd_agent.core.orchestrator import run_simulation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cfd-agent", description="Run CFD Agent workflows")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="Run a simulation workflow")
    run_parser.add_argument("--input", required=True, help="Path to SimulationTask JSON")
    run_parser.add_argument("--output", required=True, help="Output directory")
    run_parser.add_argument("--dry-run", action="store_true", help="Validate and generate plans without external solvers")
    run_parser.add_argument("--from-stage", help="First stage to run when resuming a segmented workflow")
    run_parser.add_argument("--to-stage", help="Last stage to run for segmented workflow execution")
    run_parser.add_argument("--json", action="store_true", help="Print full workflow result JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        task = load_simulation_task(args.input)
        result = run_simulation(task, args.output, dry_run=args.dry_run, from_stage=args.from_stage, to_stage=args.to_stage)
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            report = result.get("files", {}).get("report")
            print(f"Task ID: {result['task_id']}")
            print(f"Status: {result['status']}")
            print(f"Stage: {result['stage']}")
            print(f"Report: {Path(report) if report else ''}")
        return 0 if result["status"] == "success" else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
