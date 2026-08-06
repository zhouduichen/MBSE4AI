from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from rflp_lite import __version__
from rflp_lite.adapters.sqlite_repository import SQLiteRepository
from rflp_lite.adapters.test_executor import DEFAULT_TEST_TIMEOUT
from rflp_lite.application.demo import PROJECT_ROOT, run_demo
from rflp_lite.application.project_bridge import (
    analyze_project_state,
    approve_workbench_baseline,
    execute_tests_state,
    verify_contracts_state,
)
from rflp_lite.application.requirements_workbench import (
    accept_traceable,
    analyze_artifact,
    generate_model,
    merge_artifact,
)
from rflp_lite.application.workspaces import initialize_workspace
from rflp_lite.domain.canonical import canonical_json
from rflp_lite.domain.errors import ContractViolation, RflpError
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
    web_parser = subparsers.add_parser("web", help="start the local Web UI")
    web_parser.add_argument("--host", default="127.0.0.1")
    web_parser.add_argument("--port", type=int, default=8000)
    web_parser.add_argument(
        "--workspace-root", type=Path, default=PROJECT_ROOT / "workspaces"
    )
    project_parser = subparsers.add_parser(
        "project", help="connect a local Python project to the approved baseline"
    )
    project_commands = project_parser.add_subparsers(dest="project_command", required=True)
    project_approve = project_commands.add_parser(
        "approve", help="approve the workbench RFLP as the baseline"
    )
    project_approve.add_argument("--workspace", type=Path, required=True)
    project_analyze = project_commands.add_parser(
        "analyze", help="scan a local Python project and diff it against the approved baseline"
    )
    project_analyze.add_argument("--workspace", type=Path, required=True)
    project_analyze.add_argument("--source", required=True)
    project_verify = project_commands.add_parser(
        "verify", help="re-scan the project and report which task contracts are satisfied"
    )
    project_verify.add_argument("--workspace", type=Path, required=True)
    project_verify.add_argument("--source", required=True)
    project_test = project_commands.add_parser(
        "test", help="run the project's pytest suite in a timeout-and-isolation sandbox"
    )
    project_test.add_argument("--workspace", type=Path, required=True)
    project_test.add_argument("--source", required=True)
    project_test.add_argument("--timeout", type=int, default=DEFAULT_TEST_TIMEOUT)
    workbench_parser = subparsers.add_parser(
        "workbench", help="build the requirements workbench headlessly"
    )
    workbench_commands = workbench_parser.add_subparsers(
        dest="workbench_command", required=True
    )
    workbench_build = workbench_commands.add_parser(
        "build", help="analyze + accept + generate RFLP from a requirements file"
    )
    workbench_build.add_argument("--workspace", type=Path, required=True)
    workbench_build.add_argument(
        "--requirements", type=Path, nargs="+", required=True,
        help="一个或多个需求文件；首个创建，其余并入",
    )
    assess_parser = subparsers.add_parser(
        "assess", help="one-shot: requirements + project -> baseline/delta/tasks/test report"
    )
    assess_parser.add_argument("--workspace", type=Path, required=True)
    assess_parser.add_argument("--requirements", type=Path, required=True)
    assess_parser.add_argument("--source", required=True)
    assess_parser.add_argument("--timeout", type=int, default=DEFAULT_TEST_TIMEOUT)
    args = parser.parse_args(argv)
    if args.command == "version":
        print(f"rflp-lite {__version__}")
        return 0
    try:
        if args.command == "web":
            try:
                serve_web(args.host, args.port, args.workspace_root.resolve())
            except ModuleNotFoundError:
                print(
                    "Web dependencies are missing. Install with: "
                    "pip install -e '.[web]'",
                    file=sys.stderr,
                )
                return 1
            return 0
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
        if args.command == "project":
            return _run_project(args)
        if args.command == "workbench":
            return _run_workbench(args)
        if args.command == "assess":
            return _run_assess(args)
    except (RflpError, OSError) as exc:
        print(
            canonical_json(
                {"status": "failed", "error": type(exc).__name__, "message": str(exc)}
            ),
            file=sys.stderr,
        )
        return 1
    return 2


def _run_workbench(args: argparse.Namespace) -> int:
    workspace = args.workspace.resolve()
    state = None
    for path in args.requirements:
        content = path.read_bytes()
        if state is None:
            state = analyze_artifact(path.name, content)
        else:
            state = merge_artifact(state, path.name, content)
    state = accept_traceable(state)
    state = generate_model(state)
    repository = SQLiteRepository(workspace / ".rflp" / "model.db")
    try:
        with repository.transaction():
            repository.save_workbench(state)
            for event in ("requirements.analyzed", "requirements.accepted", "requirements.generated"):
                repository.record_audit(event, {"artifact": state["artifact"]["path"]})
    finally:
        repository.close()
    print(
        canonical_json(
            {
                "status": "ok",
                "artifact": state["artifact"]["path"],
                "requirements": len(state["claims"]),
                "rflp_elements": len(state["rflp"]["elements"]),
                "rflp_relations": len(state["rflp"]["relations"]),
            }
        )
    )
    return 0


def _run_assess(args: argparse.Namespace) -> int:
    workspace = args.workspace.resolve()
    content = args.requirements.read_bytes()
    state = analyze_artifact(args.requirements.name, content)
    state = accept_traceable(state)
    state = generate_model(state)
    state, baseline = approve_workbench_baseline(state)
    state, artifacts = analyze_project_state(state, args.source)
    state, verify = execute_tests_state(state, args.source, args.timeout)
    execution_summary = state["project"]["execution"]["summary"]
    test_run = execution_summary["test_run"]
    repository = SQLiteRepository(workspace / ".rflp" / "model.db")
    try:
        with repository.transaction():
            repository.save_workbench(state)
            repository.save_baseline(baseline)
            repository.save_tasks(artifacts.tasks)
            repository.save_evidence(verify.evidence)
            for event, payload in (
                ("requirements.analyzed", {"artifact": state["artifact"]["path"]}),
                ("requirements.generated", {"artifact": state["artifact"]["path"]}),
                ("baseline.approved", {"baseline_hash": baseline.hash}),
                ("project.analyzed", {"source": str(state["project"]["source"])}),
                (
                    "project.tested",
                    {
                        "source": str(state["project"]["execution"]["source"]),
                        "returncode": test_run["returncode"],
                        "timed_out": test_run["timed_out"],
                        "tests_passed": test_run["tests_passed"],
                        "tests_failed": test_run["tests_failed"],
                    },
                ),
            ):
                repository.record_audit(event, payload)
    finally:
        repository.close()
    print(
        canonical_json(
            {
                "status": "ok",
                "baseline_hash": baseline.hash,
                "actual_model_id": artifacts.actual.id,
                "matched": execution_summary["matched"],
                "missing": execution_summary["missing"],
                "extra": execution_summary["extra"],
                "tasks": len(artifacts.tasks),
                "resolved": execution_summary["resolved"],
                "unresolved": execution_summary["unresolved"],
                "tests_passed": test_run["tests_passed"],
                "tests_failed": test_run["tests_failed"],
                "timed_out": test_run["timed_out"],
            }
        )
    )
    return 0


def _run_project(args: argparse.Namespace) -> int:
    workspace = args.workspace.resolve()
    repository = SQLiteRepository(workspace / ".rflp" / "model.db")
    try:
        state = repository.load_workbench()
        if state is None:
            raise ContractViolation("需求工作台为空，请先在需求建模中生成并批准 RFLP")
        if args.project_command == "approve":
            state, baseline = approve_workbench_baseline(state)
            with repository.transaction():
                repository.save_workbench(state)
                repository.save_baseline(baseline)
                repository.record_audit(
                    "baseline.approved", {"baseline_hash": baseline.hash}
                )
            print(
                canonical_json(
                    {
                        "status": "ok",
                        "baseline_id": baseline.id,
                        "baseline_hash": baseline.hash,
                    }
                )
            )
            return 0
        if args.project_command == "verify":
            state, verify = verify_contracts_state(state, args.source)
            summary = state["project"]["execution"]["summary"]
            with repository.transaction():
                repository.save_workbench(state)
                repository.save_evidence(verify.evidence)
                repository.record_audit(
                    "project.executed",
                    {
                        "source": str(state["project"]["execution"]["source"]),
                        "resolved": summary["resolved"],
                        "unresolved": summary["unresolved"],
                        "missing": summary["missing"],
                        "extra": summary["extra"],
                    },
                )
            print(
                canonical_json(
                    {
                        "status": "ok",
                        "actual_model_id": verify.model.id,
                        "resolved": summary["resolved"],
                        "unresolved": summary["unresolved"],
                        "missing": summary["missing"],
                        "extra": summary["extra"],
                    }
                )
            )
            return 0
        if args.project_command == "test":
            state, verify = execute_tests_state(state, args.source, args.timeout)
            execution_summary = state["project"]["execution"]["summary"]
            test_run = execution_summary["test_run"]
            with repository.transaction():
                repository.save_workbench(state)
                repository.save_evidence(verify.evidence)
                repository.record_audit(
                    "project.tested",
                    {
                        "source": str(state["project"]["execution"]["source"]),
                        "returncode": test_run["returncode"],
                        "timed_out": test_run["timed_out"],
                        "tests_passed": test_run["tests_passed"],
                        "tests_failed": test_run["tests_failed"],
                    },
                )
            print(
                canonical_json(
                    {
                        "status": "ok",
                        "actual_model_id": verify.model.id,
                        "returncode": test_run["returncode"],
                        "timed_out": test_run["timed_out"],
                        "tests_passed": test_run["tests_passed"],
                        "tests_failed": test_run["tests_failed"],
                        "failed_tests": test_run["failed_tests"],
                        "resolved": execution_summary["resolved"],
                        "unresolved": execution_summary["unresolved"],
                    }
                )
            )
            return 0
        state, artifacts = analyze_project_state(state, args.source)
        summary = state["project"]["summary"]
        with repository.transaction():
            repository.save_workbench(state)
            repository.save_baseline(artifacts.baseline)
            repository.save_evidence(artifacts.evidence)
            repository.save_tasks(artifacts.tasks)
            repository.record_audit(
                "project.analyzed",
                {
                    "source": str(state["project"]["source"]),
                    "missing": summary["missing"],
                    "extra": summary["extra"],
                    "tasks": len(artifacts.tasks),
                },
            )
        print(
            canonical_json(
                {
                    "status": "ok",
                    "baseline_hash": artifacts.baseline.hash,
                    "actual_model_id": artifacts.actual.id,
                    "files_used": summary["files_used"],
                    "matched": summary["matched"],
                    "missing": summary["missing"],
                    "extra": summary["extra"],
                    "tasks": len(artifacts.tasks),
                }
            )
        )
        return 0
    finally:
        repository.close()


def serve_web(host: str, port: int, workspace_root: Path) -> None:
    import uvicorn

    from rflp_lite.interface.web.app import create_app

    uvicorn.run(create_app(workspace_root=workspace_root), host=host, port=port)


def entrypoint() -> None:
    raise SystemExit(main())
