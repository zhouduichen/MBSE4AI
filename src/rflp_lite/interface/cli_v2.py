"""Resource-oriented ``ai4mbse`` command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.application.llm_profiles import default_config_dir
from rflp_lite.application.model_export import graph_sysml
from rflp_lite.domain.canonical import canonical_json
from rflp_lite.domain.errors import RflpError
from rflp_lite.methodology.contracts import Phase


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai4mbse", description="AI4MBSE 本地模型工程工作台")
    parser.add_argument("--workspace-root", type=Path, default=Path("workspaces"), help="项目工作区根目录")
    commands = parser.add_subparsers(dest="command", required=True)
    project = commands.add_parser("project", help="创建、导入和管理项目")
    project_commands = project.add_subparsers(dest="project_command", required=True)
    create = project_commands.add_parser("create", help="创建项目")
    create.add_argument("project_id", help="项目标识")
    create.add_argument("--name", default="", help="项目显示名称")
    ingest = project_commands.add_parser("ingest", help="导入需求或模型文件")
    ingest.add_argument("project_id", help="项目标识")
    ingest.add_argument("path", type=Path, help="待导入文件路径")
    analyze = commands.add_parser("analyze", help="运行分析与查看运行状态")
    analyze_commands = analyze.add_subparsers(dest="analyze_command", required=True)
    run = analyze_commands.add_parser("run", help="运行完整生命周期或单个阶段")
    run.add_argument("project_id", help="项目标识")
    run.add_argument("--phase", choices=[phase.value for phase in Phase if phase is not Phase.CLOSURE], default=None, help="仅运行单阶段；省略则执行完整生命周期")
    status = analyze_commands.add_parser("status", help="查看运行台账")
    status.add_argument("project_id", help="项目标识")
    status.add_argument("run_id", help="运行标识")
    model = commands.add_parser("model", help="读取和导出模型")
    model_commands = model.add_subparsers(dest="model_command", required=True)
    export = model_commands.add_parser("export", help="导出模型视图")
    export.add_argument("project_id", help="项目标识")
    export.add_argument("--view", default="rflp", help="模型视图标识")
    export.add_argument("--format", choices=("json", "dot", "svg", "sysml"), default="json", help="导出格式")
    issue = commands.add_parser("issue", help="查看模型问题")
    issue_commands = issue.add_subparsers(dest="issue_command", required=True)
    issue_list = issue_commands.add_parser("list", help="列出项目问题")
    issue_list.add_argument("project_id", help="项目标识")
    repair = commands.add_parser("repair", help="执行定向修复")
    repair_commands = repair.add_subparsers(dest="repair_command", required=True)
    repair_run = repair_commands.add_parser("run", help="修复指定问题")
    repair_run.add_argument("project_id", help="项目标识")
    repair_run.add_argument("issue_id", help="问题标识")
    profile = commands.add_parser("model-profile", help="管理模型服务配置")
    profile_commands = profile.add_subparsers(dest="profile_command", required=True)
    profile_commands.add_parser("list", help="列出模型配置")
    profile_save = profile_commands.add_parser("save", help="保存模型配置")
    profile_save.add_argument("payload", type=Path, help="配置 JSON 文件路径")
    profile_activate = profile_commands.add_parser("activate", help="激活模型配置")
    profile_activate.add_argument("profile_id", help="配置标识")
    return parser


def _graph_sysml(graph) -> str:
    return graph_sysml(graph)


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
            raise RflpError(f"未找到运行记录：{args.run_id}")
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
    raise RflpError("不支持的 ai4mbse 命令")


def entrypoint() -> None:
    try:
        raise SystemExit(main())
    except RflpError as exc:
        print(canonical_json({"status": "failed", "error": type(exc).__name__, "message": str(exc)}), file=sys.stderr)
        raise SystemExit(1) from exc
