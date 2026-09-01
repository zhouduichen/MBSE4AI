from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from rflp_lite import __version__
from rflp_lite.application.dependencies import configured_dependencies
from rflp_lite.ports.test_execution import DEFAULT_TEST_TIMEOUT, build_limits
from rflp_lite.application.demo import run_demo
from rflp_lite.application.acceptance_harness import run_customer_acceptance
from rflp_lite.application.mbse_exchange import export_mbse_json, export_mbse_sysml_v2_text
from rflp_lite.application.mbse_modeling import apply_mbse_edit, generate_mbse_revision
from rflp_lite.application.mbse_render import render_mbse_svg
from rflp_lite.application.profile_packs import (
    export_run_record,
    load_profile,
    save_profile,
    validate_profile_payload,
)
from rflp_lite.application.resources import default_workspace_root, resource_path
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
from rflp_lite.application.workbench_schema import migrate_workbench_state
from rflp_lite.application.scenario_execution import append_scenario_run, execute_scenario
from rflp_lite.application.run_catalog import load_run
from rflp_lite.application.sysml_v2 import export_sysml_v2_text, import_sysml_v2_text
from rflp_lite.application.workspaces import initialize_workspace
from rflp_lite.application.web_facade import WebFacade
from rflp_lite.application.domain_packs import load_domain_pack
from rflp_lite.application.discipline_batch import validate_evaluator_profile
from rflp_lite.domain.canonical import canonical_json
from rflp_lite.domain.errors import ContractViolation, RflpError
from rflp_lite.governance.profile import Profile
from rflp_lite.governance.validation import validate_json
from rflp_lite.bootstrap.container import build_container


def _save_workbench(repository, state: dict[str, object], event: str = "workbench.saved"):
    expected_revision = int(state.get("revision", 0) or 0)
    expected_content_revision = int(
        state.get("content_revision", state.get("revision", 0)) or 0
    )
    return repository.save_workbench(
        state,
        event,
        expected_revision=expected_revision,
        expected_content_revision=expected_content_revision,
    )


def main(argv: Sequence[str] | None = None) -> int:
    build_container(Path.cwd())
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
        "--workspace-root", type=Path, default=default_workspace_root()
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
    _add_test_options(project_test)
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
    discover_parser = subparsers.add_parser("discover", help="从稀疏输入生成可审核 MBSE 候选")
    discover_commands = discover_parser.add_subparsers(dest="discover_command", required=True)
    discover_draft = discover_commands.add_parser("draft")
    discover_draft.add_argument("--workspace", type=Path, required=True)
    discover_draft.add_argument("--pack", default="urban-medical-aam-v1")
    discover_draft.add_argument(
        "--input", type=Path, nargs="+", metavar="FILE",
        help="需求/工程资料文件；提供后从稀疏输入直接建立发现工作台",
    )
    discover_review = discover_commands.add_parser("review")
    discover_review.add_argument("--workspace", type=Path, required=True)
    discover_review.add_argument("--candidate-id", required=True)
    discover_review.add_argument("--decision", choices=("accepted", "rejected"), required=True)
    discover_review.add_argument("--revision", type=int, required=True)
    discover_review.add_argument("--pack", default="urban-medical-aam-v1")
    discover_finalize = discover_commands.add_parser("finalize")
    discover_finalize.add_argument("--workspace", type=Path, required=True)
    discover_finalize.add_argument("--pack", default="urban-medical-aam-v1")
    discover_export = discover_commands.add_parser("export")
    discover_export.add_argument("--workspace", type=Path, required=True)
    discover_export.add_argument("--pack", default="urban-medical-aam-v1")
    discover_export.add_argument("--diagram", default="environment")
    discover_export.add_argument("--page", type=int)
    assess_parser = subparsers.add_parser(
        "assess", help="one-shot: requirements + project -> baseline/delta/tasks/test report"
    )
    assess_parser.add_argument("--workspace", type=Path, required=True)
    assess_parser.add_argument("--requirements", type=Path, required=True)
    assess_parser.add_argument("--source", required=True)
    assess_parser.add_argument("--timeout", type=int, default=DEFAULT_TEST_TIMEOUT)
    _add_test_options(assess_parser)
    profile_parser = subparsers.add_parser("profile", help="validate or edit a local Profile JSON")
    profile_commands = profile_parser.add_subparsers(dest="profile_command", required=True)
    profile_show = profile_commands.add_parser("show")
    profile_show.add_argument("--workspace", type=Path, required=True)
    profile_validate = profile_commands.add_parser("validate")
    profile_validate.add_argument("--profile", type=Path, required=True)
    profile_save = profile_commands.add_parser("save")
    profile_save.add_argument("--workspace", type=Path, required=True)
    profile_save.add_argument("--profile", type=Path, required=True)
    scenario_parser = subparsers.add_parser("scenario", help="execute a structured scenario trace")
    scenario_commands = scenario_parser.add_subparsers(dest="scenario_command", required=True)
    scenario_execute = scenario_commands.add_parser("execute")
    scenario_execute.add_argument("--workspace", type=Path, required=True)
    scenario_execute.add_argument("--scenario-id", required=True)
    run_parser = subparsers.add_parser("run", help="export a local run record")
    run_commands = run_parser.add_subparsers(dest="run_command", required=True)
    run_export = run_commands.add_parser("export")
    run_export.add_argument("--workspace", type=Path, required=True)
    run_export.add_argument("--result-hash", required=True)
    sysml_parser = subparsers.add_parser("sysml", help="export or import the RFLP SysML v2 subset")
    sysml_commands = sysml_parser.add_subparsers(dest="sysml_command", required=True)
    sysml_export = sysml_commands.add_parser("export")
    sysml_export.add_argument("--workspace", type=Path, required=True)
    sysml_import = sysml_commands.add_parser("import")
    sysml_import.add_argument("--workspace", type=Path, required=True)
    sysml_import.add_argument("--file", type=Path, required=True)
    mbse_parser = subparsers.add_parser("mbse", help="generate or export semantic MBSE views")
    mbse_commands = mbse_parser.add_subparsers(dest="mbse_command", required=True)
    mbse_generate = mbse_commands.add_parser("generate")
    mbse_generate.add_argument("--workspace", type=Path, required=True)
    mbse_confirm = mbse_commands.add_parser("confirm")
    mbse_confirm.add_argument("--workspace", type=Path, required=True)
    mbse_export = mbse_commands.add_parser("export")
    mbse_export.add_argument("--workspace", type=Path, required=True)
    mbse_export.add_argument("--format", choices=("json", "sysml", "svg"), default="json")
    mbse_export.add_argument("--view", choices=("all", "use_case", "activity", "sequence"), default="all")
    acceptance_parser = subparsers.add_parser("acceptance", help="run customer requirements/MBSE acceptance checks")
    acceptance_parser.add_argument("--requirements", type=Path, required=True)
    acceptance_parser.add_argument("--gold", type=Path)
    concept_parser = subparsers.add_parser("concept", help="run the lightweight concept-layout workflow")
    concept_commands = concept_parser.add_subparsers(dest="concept_command", required=True)
    concept_import = concept_commands.add_parser("import")
    concept_import.add_argument("--workspace", type=Path, required=True)
    concept_import.add_argument("--pack", type=Path, required=True)
    concept_import.add_argument("--data", type=Path, required=True)
    concept_import.add_argument("--table")
    concept_run = concept_commands.add_parser("run")
    concept_run.add_argument("--workspace", type=Path, required=True)
    concept_run.add_argument("--pack", type=Path, required=True)
    concept_run.add_argument("--evaluator-profile", type=Path, required=True)
    concept_run.add_argument("--envelope", type=Path, required=True)
    concept_run.add_argument("--iterations", type=int, default=3)
    concept_run.add_argument("--evaluation-budget", type=int, default=30)
    concept_run.add_argument("--no-optimize", action="store_true")
    concept_export = concept_commands.add_parser("export")
    concept_export.add_argument("--workspace", type=Path, required=True)
    concept_export.add_argument("--run-id", required=True)
    concept_export.add_argument("--format", choices=("json", "svg"), default="json")
    concept_export.add_argument("--candidate-id")
    concept_review = concept_commands.add_parser("review")
    concept_review.add_argument("--workspace", type=Path, required=True)
    concept_review.add_argument("--run-id", default="")
    concept_review.add_argument("--candidate-id", required=True)
    concept_review.add_argument("--decision", choices=("accepted", "rejected"), required=True)
    concept_acceptance = concept_commands.add_parser("acceptance")
    concept_acceptance.add_argument("--pack", type=Path, required=True)
    concept_acceptance.add_argument("--schemes", type=Path, required=True)
    concept_acceptance.add_argument("--envelope", type=Path, required=True)
    concept_acceptance.add_argument("--evaluator-profile", type=Path, required=True)
    mlflow_parser = subparsers.add_parser("mlflow", help="track a local run in MLflow")
    mlflow_parser.add_argument("--workspace", type=Path, required=True)
    mlflow_parser.add_argument("--result-hash", required=True)
    mlflow_parser.add_argument("--tracking-uri")
    mlflow_parser.add_argument("--experiment", default="rflp-lite")
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
                profile.as_dict(), resource_path("schemas/profile.schema.json")
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
        if args.command == "discover":
            return _run_discover(args)
        if args.command == "assess":
            return _run_assess(args)
        if args.command == "profile":
            return _run_profile(args)
        if args.command == "scenario":
            return _run_scenario(args)
        if args.command == "run":
            return _run_run(args)
        if args.command == "sysml":
            return _run_sysml(args)
        if args.command == "mbse":
            return _run_mbse(args)
        if args.command == "acceptance":
            report = run_customer_acceptance(args.requirements.name, args.requirements.read_bytes(), args.gold)
            print(canonical_json(report))
            return 0 if report["status"] == "passed" else 1
        if args.command == "concept":
            return _run_concept(args)
        if args.command == "mlflow":
            return _run_mlflow(args)
    except (RflpError, OSError) as exc:
        print(
            canonical_json(
                {"status": "failed", "error": type(exc).__name__, "message": str(exc)}
            ),
            file=sys.stderr,
        )
        return 1
    return 2


def _run_profile(args: argparse.Namespace) -> int:
    if args.profile_command == "show":
        print(canonical_json(load_profile(args.workspace.resolve())))
        return 0
    payload = json.loads(args.profile.read_text(encoding="utf-8"))
    normalized = validate_profile_payload(payload)
    if args.profile_command == "save":
        normalized = save_profile(args.workspace.resolve(), normalized)
    print(canonical_json({"status": "ok", "profile": normalized}))
    return 0


def _run_concept(args: argparse.Namespace) -> int:
    if args.concept_command == "acceptance":
        from rflp_lite.application.concept_acceptance import run_concept_acceptance

        report = run_concept_acceptance(
            args.pack, args.schemes, args.envelope, args.evaluator_profile
        )
        print(canonical_json(report))
        return 0 if report["status"] == "passed" else 1
    if args.concept_command == "import":
        pack = load_domain_pack(args.pack)
        if args.data.suffix.casefold() in {".db", ".sqlite", ".sqlite3"}:
            if not args.table:
                raise ContractViolation("--table is required for SQLite scheme import")
            rows = configured_dependencies().sqlite_scheme_reader(args.data, args.table)
        else:
            rows = configured_dependencies().scheme_reader(args.data.name, args.data.read_bytes())
        from rflp_lite.application.scheme_library import import_scheme_rows

        imported = import_scheme_rows(pack, rows, str(args.data))
        repository = configured_dependencies().repository_factory(args.workspace / ".rflp" / "model.db")
        try:
            with repository.transaction():
                repository.save_domain_pack(pack)
                repository.save_scheme_records(imported.records)
                repository.record_audit("concept.schemes_imported", {
                    "source": str(args.data), "accepted": len(imported.records), "rejected": len(imported.rejected)
                })
        finally:
            repository.close()
        print(canonical_json(imported))
        return 0
    if args.concept_command == "run":
        profile = validate_evaluator_profile(json.loads(args.evaluator_profile.read_text(encoding="utf-8")))
        facade = WebFacade(args.workspace.parent)
        result = facade.run_concept_design(
            args.workspace.name,
            args.pack,
            profile,
            json.loads(args.envelope.read_text(encoding="utf-8")),
            optimize=not args.no_optimize,
        )
        print(canonical_json({
            "status": result["status"],
            "run_id": result["id"],
            "candidate_count": len(result["candidates"]),
            "disciplines": sorted({item["discipline"] for item in result["evaluations"]}),
            "formal_status": result.get("formal_status", "development"),
        }))
        return 0
    if args.concept_command == "export":
        repository = configured_dependencies().repository_factory(args.workspace / ".rflp" / "model.db")
        try:
            payload = repository.load_concept_run(args.run_id)
        finally:
            repository.close()
        if payload is None:
            raise ContractViolation(f"concept run not found: {args.run_id}")
        if args.format == "json":
            print(canonical_json(payload))
            return 0
        if not args.candidate_id:
            raise ContractViolation("--candidate-id is required for SVG export")
        candidate = next((item for item in payload.get("candidates", ()) if item.get("id") == args.candidate_id), None)
        if candidate is None:
            raise ContractViolation(f"layout candidate not found: {args.candidate_id}")
        print(str(candidate.get("svg", "")))
        return 0
    if args.concept_command == "review":
        facade = WebFacade(args.workspace.parent)
        review = facade.review_layout_candidate(
            args.workspace.name,
            args.candidate_id,
            args.decision,
            run_id=args.run_id,
        )
        print(canonical_json(review))
        return 0
    raise ContractViolation("unknown concept command")


def _run_scenario(args: argparse.Namespace) -> int:
    workspace = args.workspace.resolve()
    repository = configured_dependencies().repository_factory(workspace / ".rflp" / "model.db")
    try:
        state = repository.load_workbench()
        if state is None:
            raise ContractViolation("需求工作台为空")
        service = configured_dependencies().job_service_factory(workspace)
        job = service.submit(
            "scenario.execute",
            {"scenario_id": args.scenario_id},
            lambda: execute_scenario(state, args.scenario_id),
        )
        result = job["result"]
        state = append_scenario_run(state, result)
        with repository.transaction():
            _save_workbench(repository, state)
            repository.record_audit(
                "scenario.executed",
                {
                    "scenario_id": args.scenario_id,
                    "run_id": result["run_id"],
                    "status": result["status"],
                },
            )
        print(canonical_json({**result, "job": {"id": job["id"], "status": job["status"]}}))
        return 0
    finally:
        repository.close()


def _run_run(args: argparse.Namespace) -> int:
    if args.run_command != "export":
        return 2
    record = load_run(args.workspace.resolve(), args.result_hash)
    print(canonical_json(export_run_record(record)))
    return 0


def _run_sysml(args: argparse.Namespace) -> int:
    workspace = args.workspace.resolve()
    repository = configured_dependencies().repository_factory(workspace / ".rflp" / "model.db")
    try:
        state = repository.load_workbench()
        if state is None:
            raise ContractViolation("需求工作台为空")
        if args.sysml_command == "export":
            if not state.get("rflp"):
                raise ContractViolation("RFLP model not generated")
            print(export_sysml_v2_text(state["rflp"]), end="")
            return 0
        state["rflp"] = import_sysml_v2_text(args.file.read_text(encoding="utf-8"))
        with repository.transaction():
            _save_workbench(repository, state)
            repository.record_audit("rflp.sysml_v2_imported", {"file": str(args.file)})
        print(canonical_json({"status": "ok", "elements": len(state["rflp"]["elements"]), "relations": len(state["rflp"]["relations"])}))
        return 0
    finally:
        repository.close()


def _run_mbse(args: argparse.Namespace) -> int:
    workspace = args.workspace.resolve()
    repository = configured_dependencies().repository_factory(workspace / ".rflp" / "model.db")
    try:
        state = repository.load_workbench()
        if state is None:
            raise ContractViolation("需求工作台为空")
        if args.mbse_command == "generate":
            state = generate_mbse_revision(state)
            with repository.transaction():
                _save_workbench(repository, state, "requirements.mbse_generated")
                repository.record_audit("requirements.mbse_generated", {})
            print(canonical_json({"status": "ok", "revision": state["mbse"]["revision"]}))
            return 0
        if args.mbse_command == "confirm":
            from rflp_lite.application.mbse_modeling import confirm_mbse

            state = confirm_mbse(state)
            with repository.transaction():
                _save_workbench(repository, state, "requirements.mbse_confirmed")
                repository.record_audit("requirements.mbse_confirmed", {})
            print(canonical_json({"status": "ok", "revision": state["mbse"]["revision"], "model_status": state["mbse"]["status"]}))
            return 0
        model = state.get("mbse")
        if not model:
            raise ContractViolation("MBSE semantic model not generated")
        if model.get("status") != "accepted":
            raise ContractViolation("MBSE 模型尚未确认，确认后才能导出")
        if args.format == "json":
            print(canonical_json(export_mbse_json(model)))
        elif args.format == "sysml":
            print(export_mbse_sysml_v2_text(model), end="")
        else:
            print(render_mbse_svg(model, args.view))
        return 0
    finally:
        repository.close()


def _run_mlflow(args: argparse.Namespace) -> int:
    record = load_run(args.workspace.resolve(), args.result_hash)
    result = configured_dependencies().tracking(
        record,
        tracking_uri=args.tracking_uri,
        experiment_name=args.experiment,
    )
    print(canonical_json(result))
    return 0 if result["status"] != "failed" else 1


def _run_discover(args: argparse.Namespace) -> int:
    facade = WebFacade(args.workspace.parent)
    workspace_name = args.workspace.name
    if args.discover_command == "draft":
        if getattr(args, "input", None):
            workspace = args.workspace.resolve()
            try:
                WebFacade(args.workspace.parent).workspace(workspace_name)
            except ContractViolation:
                initialize_workspace(workspace)
            state = None
            for path in args.input:
                content = path.read_bytes()
                state = (
                    analyze_artifact(path.name, content)
                    if state is None
                    else merge_artifact(state, path.name, content)
                )
            state = migrate_workbench_state(state)
            repository = configured_dependencies().repository_factory(workspace / ".rflp" / "model.db")
            try:
                with repository.transaction():
                    _save_workbench(repository, state, "requirements.analyzed")
                    repository.record_audit(
                        "requirements.analyzed",
                        {"artifact": state["artifact"]["path"]},
                    )
            finally:
                repository.close()
        state = facade.draft_discovery(workspace_name, args.pack)
        discovery = state.get("discovery", {})
        print(canonical_json({"status": "ok", "revision": discovery.get("revision", 0), "candidate_count": sum(len(group.get("items", [])) for group in discovery.get("candidate_sets", []) if isinstance(group, dict)), "coverage": discovery.get("coverage", {})}))
        return 0
    if args.discover_command == "review":
        state = facade.review_discovery(workspace_name, args.candidate_id, args.decision, args.revision, args.pack)
        print(canonical_json({"status": "ok", "revision": state.get("discovery", {}).get("revision", 0)}))
        return 0
    if args.discover_command == "finalize":
        state = facade.finalize_discovery(workspace_name, args.pack)
        print(canonical_json({"status": "ok", "revision": state.get("discovery", {}).get("revision", 0), "accepted_graph": state.get("discovery", {}).get("accepted_graph", {})}))
        return 0
    if args.discover_command == "export":
        pages = facade.render_discovery_diagram(workspace_name, args.pack, args.diagram)
        if len(pages) > 1 and args.page is None:
            raise ContractViolation("diagram has multiple pages; use --page")
        page = (args.page or 1) - 1
        if page < 0 or page >= len(pages):
            raise ContractViolation("diagram page is out of range")
        sys.stdout.buffer.write(pages[page].content)
        return 0
    raise ContractViolation("unknown discover command")


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
    repository = configured_dependencies().repository_factory(workspace / ".rflp" / "model.db")
    try:
        with repository.transaction():
            _save_workbench(repository, state)
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
    state, verify = execute_tests_state(
        state, args.source, args.timeout, **_test_options(args, workspace)
    )
    execution_summary = state["project"]["execution"]["summary"]
    test_run = execution_summary["test_run"]
    repository = configured_dependencies().repository_factory(workspace / ".rflp" / "model.db")
    try:
        with repository.transaction():
            _save_workbench(repository, state)
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
                        "runner": test_run["runner"],
                        "cache_hit": test_run["cache_hit"],
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
                "runner": test_run["runner"],
                "runners": test_run["runners"],
                "jobs": test_run["jobs"],
                "cache_hit": test_run["cache_hit"],
                "resource_limits": test_run["resource_limits"],
            }
        )
    )
    return 0


def _run_project(args: argparse.Namespace) -> int:
    workspace = args.workspace.resolve()
    repository = configured_dependencies().repository_factory(workspace / ".rflp" / "model.db")
    try:
        state = repository.load_workbench()
        if state is None:
            raise ContractViolation("需求工作台为空，请先在需求建模中生成并批准 RFLP")
        if args.project_command == "approve":
            state, baseline = approve_workbench_baseline(state)
            with repository.transaction():
                _save_workbench(repository, state, "baseline.approved")
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
                _save_workbench(repository, state, "project.executed")
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
            state, verify = execute_tests_state(
                state, args.source, args.timeout, **_test_options(args, workspace)
            )
            execution_summary = state["project"]["execution"]["summary"]
            test_run = execution_summary["test_run"]
            with repository.transaction():
                _save_workbench(repository, state, "project.tested")
                repository.save_evidence(verify.evidence)
                repository.record_audit(
                    "project.tested",
                    {
                        "source": str(state["project"]["execution"]["source"]),
                        "returncode": test_run["returncode"],
                        "timed_out": test_run["timed_out"],
                        "tests_passed": test_run["tests_passed"],
                        "tests_failed": test_run["tests_failed"],
                        "runner": test_run["runner"],
                        "cache_hit": test_run["cache_hit"],
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
                        "runner": test_run["runner"],
                        "runners": test_run["runners"],
                        "jobs": test_run["jobs"],
                        "cache_hit": test_run["cache_hit"],
                        "resource_limits": test_run["resource_limits"],
                    }
                )
            )
            return 0
        state, artifacts = analyze_project_state(state, args.source)
        summary = state["project"]["summary"]
        with repository.transaction():
            _save_workbench(repository, state, "project.analyzed")
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


def _add_test_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--runner",
        action="append",
        choices=("pytest", "unittest"),
        help="测试运行器，可重复指定；默认 pytest",
    )
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--memory-mib", type=int, default=1024)
    parser.add_argument("--max-open-files", type=int, default=1024)
    parser.add_argument("--output-mib", type=int, default=5)
    parser.add_argument("--no-cache", action="store_true")


def _test_options(args: argparse.Namespace, workspace: Path) -> dict[str, object]:
    limits = build_limits(
        timeout_seconds=args.timeout,
        memory_mib=args.memory_mib,
        max_open_files=args.max_open_files,
        output_mib=args.output_mib,
    )
    return {
        "runners": tuple(args.runner or ("pytest",)),
        "limits": limits,
        "cache_dir": None if args.no_cache else workspace / ".rflp" / "test-cache",
        "jobs": args.jobs,
    }


def entrypoint() -> None:
    raise SystemExit(main())
