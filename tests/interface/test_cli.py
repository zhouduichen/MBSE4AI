from pathlib import Path

from rflp_lite.adapters.sqlite_repository import SQLiteRepository
from rflp_lite.application.requirements_workbench import (
    accept_traceable,
    analyze_artifact,
    generate_model,
)
from rflp_lite.application.workspaces import initialize_workspace
from rflp_lite.interface.cli import main

REQUIREMENTS = (
    "管理员必须恢复历史版本。\n"
    "The service shall restore a historical version.\n"
    "The service must record an audit event for every restore.\n"
    "审计人员必须查看恢复记录。"
)
EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "versioned-content-service"


def _workspace_with_generated_rflp(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    initialize_workspace(workspace)
    state = analyze_artifact("requirements.txt", REQUIREMENTS.encode())
    state = accept_traceable(state)
    state = generate_model(state)
    repository = SQLiteRepository(workspace / ".rflp" / "model.db")
    try:
        with repository.transaction():
            repository.save_workbench(state)
    finally:
        repository.close()
    return workspace


def test_version_command(capsys):
    assert main(["version"]) == 0
    assert capsys.readouterr().out.strip() == "rflp-lite 0.1.0"


def test_web_command_uses_safe_defaults(monkeypatch):
    captured = {}

    def fake_serve(host: str, port: int, workspace_root: Path) -> None:
        captured.update(host=host, port=port, workspace_root=workspace_root)

    monkeypatch.setattr("rflp_lite.interface.cli.serve_web", fake_serve)
    assert main(["web"]) == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8000
    assert captured["workspace_root"].name == "workspaces"


def test_web_command_reports_missing_extra(monkeypatch, capsys):
    def missing(*args, **kwargs):
        raise ModuleNotFoundError("No module named 'fastapi'")

    monkeypatch.setattr("rflp_lite.interface.cli.serve_web", missing)
    assert main(["web"]) == 1
    assert "pip install -e '.[web]'" in capsys.readouterr().err


def test_project_approve_then_analyze(tmp_path, capsys):
    workspace = _workspace_with_generated_rflp(tmp_path)

    assert main(["project", "approve", "--workspace", str(workspace)]) == 0
    approve_out = capsys.readouterr().out
    assert '"status":"ok"' in approve_out
    assert '"baseline_hash"' in approve_out

    assert main(
        ["project", "analyze", "--workspace", str(workspace), "--source", str(EXAMPLE)]
    ) == 0
    analyze_out = capsys.readouterr().out
    assert '"status":"ok"' in analyze_out
    assert '"actual_model_id"' in analyze_out
    assert '"missing"' in analyze_out
    assert '"tasks"' in analyze_out


def test_project_approve_requires_rflp(tmp_path, capsys):
    workspace = tmp_path / "ws"
    initialize_workspace(workspace)
    assert main(["project", "approve", "--workspace", str(workspace)]) == 1
    assert "需求工作台为空" in capsys.readouterr().err


def test_project_analyze_without_baseline_fails(tmp_path, capsys):
    workspace = _workspace_with_generated_rflp(tmp_path)
    assert main(
        ["project", "analyze", "--workspace", str(workspace), "--source", str(EXAMPLE)]
    ) == 1
    assert "请先批准基线" in capsys.readouterr().err


def test_project_verify_after_analyze(tmp_path, capsys):
    workspace = _workspace_with_generated_rflp(tmp_path)
    assert main(["project", "approve", "--workspace", str(workspace)]) == 0
    capsys.readouterr()
    assert main(
        ["project", "analyze", "--workspace", str(workspace), "--source", str(EXAMPLE)]
    ) == 0
    capsys.readouterr()

    assert main(
        ["project", "verify", "--workspace", str(workspace), "--source", str(EXAMPLE)]
    ) == 0
    out = capsys.readouterr().out
    assert '"status":"ok"' in out
    assert '"resolved"' in out
    assert '"unresolved"' in out


def test_project_verify_without_baseline_fails(tmp_path, capsys):
    workspace = _workspace_with_generated_rflp(tmp_path)
    assert main(
        ["project", "verify", "--workspace", str(workspace), "--source", str(EXAMPLE)]
    ) == 1
    assert "请先批准基线" in capsys.readouterr().err


def test_project_test_runs(tmp_path, capsys):
    workspace = _workspace_with_generated_rflp(tmp_path)
    assert main(["project", "approve", "--workspace", str(workspace)]) == 0
    capsys.readouterr()
    project = tmp_path / "proj"
    project.mkdir()
    (project / "test_ok.py").write_text(
        "def test_passes():\n    assert True\n", encoding="utf-8"
    )
    assert main(
        ["project", "analyze", "--workspace", str(workspace), "--source", str(project)]
    ) == 0
    capsys.readouterr()

    assert main(
        ["project", "test", "--workspace", str(workspace), "--source", str(project)]
    ) == 0
    out = capsys.readouterr().out
    assert '"status":"ok"' in out
    assert '"tests_passed":1' in out


def test_project_test_without_baseline_fails(tmp_path, capsys):
    workspace = _workspace_with_generated_rflp(tmp_path)
    project = tmp_path / "proj"
    project.mkdir()
    assert main(
        ["project", "test", "--workspace", str(workspace), "--source", str(project)]
    ) == 1
    assert "请先批准基线" in capsys.readouterr().err


def test_workbench_build_then_project_chain(tmp_path, capsys):
    workspace = tmp_path / "ws"
    initialize_workspace(workspace)
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "管理员必须恢复历史版本。\n"
        "The service shall restore a historical version.\n"
        "审计人员必须查看恢复记录。",
        encoding="utf-8",
    )

    assert main(
        ["workbench", "build", "--workspace", str(workspace), "--requirements", str(requirements)]
    ) == 0
    out = capsys.readouterr().out
    assert '"status":"ok"' in out
    assert '"rflp_elements"' in out

    assert main(["project", "approve", "--workspace", str(workspace)]) == 0
    capsys.readouterr()
    assert main(
        ["project", "analyze", "--workspace", str(workspace), "--source", str(EXAMPLE)]
    ) == 0
    capsys.readouterr()
    assert main(
        ["project", "verify", "--workspace", str(workspace), "--source", str(EXAMPLE)]
    ) == 0
    capsys.readouterr()


def test_workbench_build_without_obligations_fails(tmp_path, capsys):
    workspace = tmp_path / "ws"
    initialize_workspace(workspace)
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("没有任何义务句的内容。", encoding="utf-8")

    assert main(
        ["workbench", "build", "--workspace", str(workspace), "--requirements", str(requirements)]
    ) == 1
    assert "请先接受至少一条可追溯需求" in capsys.readouterr().err


def test_assess_one_shot_report(tmp_path, capsys):
    workspace = tmp_path / "ws"
    initialize_workspace(workspace)
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "The service shall restore a historical version.\n", encoding="utf-8"
    )
    project = tmp_path / "proj"
    project.mkdir()
    (project / "test_ok.py").write_text(
        "def test_passes():\n    assert True\n", encoding="utf-8"
    )

    assert main(
        [
            "assess",
            "--workspace",
            str(workspace),
            "--requirements",
            str(requirements),
            "--source",
            str(project),
        ]
    ) == 0
    out = capsys.readouterr().out
    assert '"status":"ok"' in out
    assert '"baseline_hash"' in out
    assert '"tests_passed":1' in out
    assert '"missing"' in out
