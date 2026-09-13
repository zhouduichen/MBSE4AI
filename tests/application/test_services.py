from pathlib import Path

from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.domain.entities import EntityKind


def test_project_service_imports_fixture_and_keeps_typed_graph(tmp_path: Path):
    services = build_v2_services(tmp_path)
    services.projects.create("p1", "项目")
    result = services.projects.seed_fixture("p1", {
        "system": "系统", "stakeholders": ["用户"], "lifecycle_stages": ["运行"],
        "scenarios": ["正常"], "requirements": [{"id": "r1", "statement": "支持配送"}],
    })

    assert result["entity_count"] == 5
    graph = services.model("p1").graph("p1")
    assert any(item.kind is EntityKind.REQUIREMENT for item in graph.entities)
    assert next(item for item in graph.entities if item.kind is EntityKind.SYSTEM).payload == {}


def test_analysis_service_runs_offline_and_view_compiles_from_graph(tmp_path: Path):
    services = build_v2_services(tmp_path)
    services.projects.create("p1")
    services.projects.seed_fixture("p1", {"system": "系统", "stakeholders": ["用户"], "lifecycle_stages": ["运行"], "scenarios": ["正常"], "requirements": []})

    result = services.analysis("p1").run("p1")
    view = services.render("p1").view("p1", "operational")

    assert result.completed_tasks
    assert view.source_graph_hash
    assert view.nodes
