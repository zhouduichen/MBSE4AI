from __future__ import annotations

import json
from pathlib import Path

from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.interface import cli_v2
from rflp_lite.runtime.rule_based import RuleRuntime, VerticalRuleRuntime


def test_cli_generate_export_and_import_sysml(tmp_path: Path, monkeypatch, capsys):
    workspace_root = tmp_path / "workspaces"

    def services_factory(root, *, config_dir=None):
        return build_v2_services(root, runtime=VerticalRuleRuntime(), config_dir=config_dir)

    monkeypatch.setattr(cli_v2, "build_v2_services", services_factory)
    root_args = ["--workspace-root", str(workspace_root)]

    assert cli_v2.main([*root_args, "project", "create", "robot"]) == 0
    capsys.readouterr()

    assert cli_v2.main([
        *root_args,
        "analyze",
        "generate",
        "robot",
        "--text",
        "系统应在校园内完成配送并允许人工接管",
    ]) == 0
    generated = json.loads(capsys.readouterr().out)
    assert generated["run"]["status"] == "completed"
    assert generated["run"]["traceability"]["complete_count"] == 1

    assert cli_v2.main([
        *root_args, "model", "export", "robot", "--format", "sysml"
    ]) == 0
    sysml = capsys.readouterr().out
    sysml_path = tmp_path / "robot.sysml"
    sysml_path.write_text(sysml, encoding="utf-8")

    assert cli_v2.main([*root_args, "project", "create", "robot-copy"]) == 0
    capsys.readouterr()
    assert cli_v2.main([
        *root_args, "model", "import-sysml", "robot-copy", str(sysml_path)
    ]) == 0
    imported = json.loads(capsys.readouterr().out)
    assert imported["status"] == "ok"
    assert imported["entity_count"] >= 7
    assert imported["relation_count"] >= 5


def test_cli_run_accepts_natural_language_input(tmp_path: Path, monkeypatch, capsys):
    workspace_root = tmp_path / "workspaces"

    def services_factory(root, *, config_dir=None):
        return build_v2_services(root, runtime=RuleRuntime(), config_dir=config_dir)

    monkeypatch.setattr(cli_v2, "build_v2_services", services_factory)
    root_args = ["--workspace-root", str(workspace_root)]

    assert cli_v2.main([*root_args, "project", "create", "robot"]) == 0
    capsys.readouterr()
    assert cli_v2.main([
        *root_args,
        "analyze",
        "run",
        "robot",
        "--text",
        "系统应支持人工接管",
    ]) == 0
    json.loads(capsys.readouterr().out)
    graph = build_v2_services(workspace_root, runtime=RuleRuntime()).repository("robot").load_graph("robot")
    assert any(item.payload.get("statement") == "系统应支持人工接管" for item in graph.entities)


def test_cli_goal_is_available_as_system_and_requirement_input(tmp_path: Path, monkeypatch, capsys):
    workspace_root = tmp_path / "workspaces"

    def services_factory(root, *, config_dir=None):
        return build_v2_services(root, runtime=RuleRuntime(), config_dir=config_dir)

    monkeypatch.setattr(cli_v2, "build_v2_services", services_factory)
    root_args = ["--workspace-root", str(workspace_root)]
    assert cli_v2.main([*root_args, "project", "create", "robot"]) == 0
    capsys.readouterr()

    assert cli_v2.main([
        *root_args,
        "analyze",
        "generate",
        "robot",
        "--goal",
        "建设可在校园内安全完成配送的系统",
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["run"]["status"] == "completed"
    graph = build_v2_services(workspace_root, runtime=RuleRuntime()).repository("robot").load_graph("robot")
    assert any(item.payload.get("source") == "user_goal" for item in graph.entities)
    system = next(item for item in graph.entities if item.kind.value == "system")
    assert system.payload["mission"] == "建设可在校园内安全完成配送的系统"
