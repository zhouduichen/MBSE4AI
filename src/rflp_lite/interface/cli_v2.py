"""Resource-oriented ``ai4mbse`` command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.application.llm_profiles import default_config_dir
from rflp_lite.domain.canonical import canonical_json
from rflp_lite.domain.errors import RflpError
from rflp_lite.methodology.contracts import Phase


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai4mbse")
    parser.add_argument("--workspace-root", type=Path, default=Path("workspaces"))
    commands = parser.add_subparsers(dest="command", required=True)
    project = commands.add_parser("project")
    project_commands = project.add_subparsers(dest="project_command", required=True)
    create = project_commands.add_parser("create")
    create.add_argument("project_id")
    create.add_argument("--name", default="")
    ingest = project_commands.add_parser("ingest")
    ingest.add_argument("project_id")
    ingest.add_argument("path", type=Path)
    analyze = commands.add_parser("analyze")
    analyze_commands = analyze.add_subparsers(dest="analyze_command", required=True)
    run = analyze_commands.add_parser("run")
    run.add_argument("project_id")
    run.add_argument("--phase", choices=[phase.value for phase in Phase if phase is not Phase.CLOSURE], default=None, help="仅运行单阶段；省略则执行完整生命周期")
    status = analyze_commands.add_parser("status")
    status.add_argument("project_id")
    status.add_argument("run_id")
    model = commands.add_parser("model")
    model_commands = model.add_subparsers(dest="model_command", required=True)
    export = model_commands.add_parser("export")
    export.add_argument("project_id")
    export.add_argument("--view", default="rflp")
    export.add_argument("--format", choices=("json", "dot", "svg", "sysml"), default="json")
    issue = commands.add_parser("issue")
    issue_commands = issue.add_subparsers(dest="issue_command", required=True)
    issue_list = issue_commands.add_parser("list")
    issue_list.add_argument("project_id")
    repair = commands.add_parser("repair")
    repair_commands = repair.add_subparsers(dest="repair_command", required=True)
    repair_run = repair_commands.add_parser("run")
    repair_run.add_argument("project_id")
    repair_run.add_argument("issue_id")
    profile = commands.add_parser("model-profile")
    profile_commands = profile.add_subparsers(dest="profile_command", required=True)
    profile_commands.add_parser("list")
    profile_save = profile_commands.add_parser("save")
    profile_save.add_argument("payload", type=Path)
    profile_activate = profile_commands.add_parser("activate")
    profile_activate.add_argument("profile_id")
    return parser


def _graph_sysml(graph) -> str:
    lines = ["package AI4MBSE_Model {", f"  // revision {graph.revision}"]
    for entity in graph.entities:
        lines.append(f'  // entity {json.dumps(entity.as_dict(), ensure_ascii=False, sort_keys=True)}')
    for relation in graph.relations:
        lines.append(f'  // relation {json.dumps({"id": relation.id, "source_id": relation.source_id, "predicate": relation.predicate.value, "target_id": relation.target_id}, ensure_ascii=False, sort_keys=True)}')
    lines.append("}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    services = build_v2_services(args.workspace_root.resolve(), config_dir=default_config_dir())
    if args.command == "project" and args.project_command == "create":
        print(canonical_json({"status": "ok", "project": services.projects.create(args.project_id, args.name)}))
        return 0
    if args.command == "project" and args.project_command == "ingest":
        print(canonical_json({"status": "ok", "document": services.projects.ingest(args.project_id, args.path)}))
        return 0
    if args.command == "analyze" and args.analyze_command == "run":
        result = services.analysis(args.project_id).run(args.project_id, Phase(args.phase) if args.phase else None)
        print(canonical_json({"status": "ok", "run": {"run_id": result.run_id, "phase": result.phase.value, "status": result.status.value, "completed_tasks": result.completed_tasks, "diagnostics": result.diagnostics}}))
        return 0
    if args.command == "analyze" and args.analyze_command == "status":
        run = services.repository(args.project_id).load_run(args.project_id, args.run_id)
        if run is None:
            raise RflpError(f"run not found: {args.run_id}")
        print(canonical_json({"status": "ok", "run": run}))
        return 0
    if args.command == "model" and args.model_command == "export":
        if args.format == "sysml":
            print(_graph_sysml(services.model(args.project_id).graph(args.project_id)), end="")
        else:
            content, _media = services.render(args.project_id).export(args.project_id, args.view, args.format)
            sys.stdout.buffer.write(content)
        return 0
    if args.command == "issue" and args.issue_command == "list":
        print(canonical_json({"status": "ok", "issues": services.model(args.project_id).issues(args.project_id)}))
        return 0
    if args.command == "repair" and args.repair_command == "run":
        result = services.analysis(args.project_id).repair(args.project_id, args.issue_id)
        print(canonical_json({"status": "ok", "run": result}))
        return 0
    if args.command == "model-profile" and args.profile_command == "list":
        print(canonical_json({"status": "ok", **services.settings.list_profiles()}))
        return 0
    if args.command == "model-profile" and args.profile_command == "save":
        payload = json.loads(args.payload.read_text(encoding="utf-8"))
        print(canonical_json({"status": "ok", "profile": services.settings.save_profile(payload)}))
        return 0
    if args.command == "model-profile" and args.profile_command == "activate":
        print(canonical_json({"status": "ok", "profile": services.settings.activate_profile(args.profile_id)}))
        return 0
    raise RflpError("unsupported ai4mbse command")


def entrypoint() -> None:
    try:
        raise SystemExit(main())
    except RflpError as exc:
        print(canonical_json({"status": "failed", "error": type(exc).__name__, "message": str(exc)}), file=sys.stderr)
        raise SystemExit(1) from exc
