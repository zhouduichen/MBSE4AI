from __future__ import annotations

import json
from pathlib import Path

from rflp_lite.application.llm_profiles import LLMProfileService
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


def test_cli_generate_selects_saved_profile_without_changing_active_profile(tmp_path: Path, monkeypatch, capsys):
    workspace_root = tmp_path / "workspaces"
    config_dir = tmp_path / "config"
    profiles = LLMProfileService(config_dir)
    profiles.save({
        "id": "local-active",
        "label": "本机配置（仅测试档案）",
        "kind": "local",
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "test-local-model",
    })
    profiles.save({
        "id": "remote-5080",
        "label": "远程 5080",
        "kind": "remote",
        "provider": "ollama",
        "base_url": "http://remote.example.invalid:11434/v1",
        "model": "qwen3.5:9b-q8_0",
    })
    captured: dict[str, object] = {}

    def services_factory(root, *, config_dir=None, runtime_config=None):
        captured["runtime_config"] = runtime_config
        services = build_v2_services(
            root,
            runtime=VerticalRuleRuntime(),
            config_dir=config_dir,
            runtime_config=runtime_config,
        )
        captured["services"] = services
        return services

    monkeypatch.setattr(cli_v2, "default_config_dir", lambda: config_dir)
    monkeypatch.setattr(cli_v2, "build_v2_services", services_factory)
    root_args = ["--workspace-root", str(workspace_root)]

    assert cli_v2.main([*root_args, "project", "create", "robot"]) == 0
    capsys.readouterr()
    assert cli_v2.main([
        *root_args,
        "analyze",
        "generate",
        "robot",
        "--profile",
        "remote-5080",
        "--text",
        "系统应支持人工接管",
    ]) == 0
    result = json.loads(capsys.readouterr().out)

    selected_config = captured["runtime_config"]
    assert isinstance(selected_config, dict)
    assert selected_config["base_url"] == "http://remote.example.invalid:11434/v1"
    selected_services = captured["services"]
    assert selected_services.repository("robot").load_run("robot", result["run"]["run_id"]).model_profile == "remote-5080"
    assert profiles.snapshot()["active_id"] == "local-active"


def test_cli_runs_registered_engineering_tool(tmp_path: Path, monkeypatch, capsys):
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
        "系统应支持人工接管",
    ]) == 0
    generated = json.loads(capsys.readouterr().out)
    graph = build_v2_services(workspace_root, runtime=VerticalRuleRuntime()).repository("robot").load_graph("robot")
    verification = next(item for item in graph.entities if item.kind.value == "verification_case")

    assert cli_v2.main([
        *root_args,
        "vv",
        "tool",
        "robot",
        verification.id,
        "model.constraint_check",
        "--expected-revision",
        str(generated["run"]["revision"]),
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["tool_execution"]["tool_id"] == "model.constraint_check"
    assert result["tool_execution"]["outcome"] == "inconclusive"
