import subprocess

from rflp_lite.adapters.graphviz_engine import GraphvizEngine
from rflp_lite.adapters.matrix_engine import MatrixEngine
from rflp_lite.adapters.plantuml_engine import PlantUMLEngine
from rflp_lite.application.mbse_modeling import generate_mbse_revision
from rflp_lite.application.mbse_render import render_mbse_view
from rflp_lite.application.requirements_workbench import accept_traceable, analyze_artifact


def _model():
    return generate_mbse_revision(
        accept_traceable(analyze_artifact("requirements.txt", "支持导入 PDF。".encode()))
    )["mbse"]


def _runner(args, **kwargs):
    assert kwargs["shell"] is False
    assert kwargs["input"]
    return subprocess.CompletedProcess(args, 0, b"<svg />", b"")


def test_graphviz_engine_uses_pipe_and_allowlisted_formats(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/local/bin/dot")
    engine = GraphvizEngine(command="dot", runner=_runner)

    result = engine.render("digraph { a -> b }", "svg")

    assert result.success is True
    assert result.media_type == "image/svg+xml"
    assert result.content == b"<svg />"
    assert engine.render("digraph {}", "pdf").success is False


def test_plantuml_engine_reports_unavailable_without_throwing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    engine = PlantUMLEngine(command="plantuml")

    result = engine.render("@startuml\nAlice -> Bob\n@enduml")

    assert result.success is False
    assert "不可用" in result.diagnostic


def test_engines_surface_timeout_and_process_diagnostics(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/local/bin/renderer")

    def timeout_runner(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("renderer", 1)

    timed_out = GraphvizEngine(command="dot", runner=timeout_runner).render("digraph {}")
    assert timed_out.success is False
    assert "超时" in timed_out.diagnostic

    def failed_runner(args, **_kwargs):
        return subprocess.CompletedProcess(args, 1, b"", "bad graph".encode())

    failed = PlantUMLEngine(command="plantuml", runner=failed_runner).render("@startuml\n@enduml")
    assert failed.success is False
    assert "bad graph" in failed.diagnostic


def test_matrix_engine_is_always_available_for_svg():
    engine = MatrixEngine()

    result = engine.render("<svg />")

    assert result.success is True
    assert result.media_type == "image/svg+xml"
    assert engine.status()["available"] is True


def test_render_falls_back_when_requested_graphviz_is_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)

    result = render_mbse_view(_model(), "rflp", engine="graphviz")

    assert result["fallback"] is True
    assert result["engine_id"] == "fallback"
    assert result["media_type"] == "image/svg+xml"
    assert result["content"].startswith(b"<svg")
