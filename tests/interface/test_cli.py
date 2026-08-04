from pathlib import Path

from rflp_lite.interface.cli import main


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
