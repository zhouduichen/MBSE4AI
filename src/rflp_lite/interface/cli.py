from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from rflp_lite import __version__
from rflp_lite.application.demo import PROJECT_ROOT, run_demo
from rflp_lite.application.workspaces import initialize_workspace
from rflp_lite.domain.canonical import canonical_json
from rflp_lite.domain.errors import RflpError
from rflp_lite.governance.profile import Profile
from rflp_lite.governance.validation import validate_json


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rflp")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("version", help="show the installed version")
    init_parser = subparsers.add_parser("init", help="initialize a local workspace")
    init_parser.add_argument("workspace", type=Path)
    demo_parser = subparsers.add_parser("demo", help="run the complete local RFLP chain")
    demo_parser.add_argument("--workspace", type=Path, required=True)
    demo_parser.add_argument("--seed", type=int, default=42)
    demo_parser.add_argument("--solver", choices=("heuristic", "cp-sat"), default="heuristic")
    demo_parser.add_argument("--candidate-limit", type=int, default=3)
    demo_parser.add_argument("--timeout-seconds", type=int, default=5)
    args = parser.parse_args(argv)
    if args.command == "version":
        print(f"rflp-lite {__version__}")
        return 0
    try:
        if args.command == "init":
            workspace = initialize_workspace(args.workspace)
            print(
                canonical_json(
                    {"profile": str(workspace.profile_path), "status": "initialized"}
                )
            )
            return 0
        if args.command == "demo":
            profile = Profile(
                solver=args.solver,
                seed=args.seed,
                candidate_limit=args.candidate_limit,
                timeout_seconds=args.timeout_seconds,
            )
            validate_json(
                profile.as_dict(), PROJECT_ROOT / "schemas" / "profile.schema.json"
            )
            result = run_demo(args.workspace.resolve(), profile)
            summary = {
                "status": "passed",
                "chain": "Artifact->TextSpan->Claim->R/F/L/P->Candidate->Simulation->Baseline->Delta->TaskContract->Evidence",
                "solver": profile.solver,
                "candidate_count": len(result.candidates),
                "claim_count": len(result.claims),
                "task_count": len(result.task_contracts),
                "evidence_count": len(result.evidence),
                "baseline_hash": result.baseline.hash,
                "result_hash": result.result_hash,
                "manifest": result.manifest_path,
            }
            print(canonical_json(summary))
            return 0
    except (RflpError, OSError) as exc:
        print(
            canonical_json(
                {"status": "failed", "error": type(exc).__name__, "message": str(exc)}
            ),
            file=sys.stderr,
        )
        return 1
    return 2


def entrypoint() -> None:
    raise SystemExit(main())
