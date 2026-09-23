from pathlib import Path

from rflp_lite.application.project_context import ProjectContextService
from rflp_lite.application.workspaces import create_managed_workspace
from rflp_lite.domain.entities import EntityKind
from rflp_lite.repository.sqlite import SQLiteModelRepository


def test_project_goal_seeds_system_intent_and_traceable_requirement(tmp_path: Path):
    root = tmp_path / "workspaces"
    create_managed_workspace(root, "p1")
    repository = SQLiteModelRepository(root / "p1" / ".rflp" / "model.db")
    repository.ensure_project("p1")

    first = ProjectContextService(repository, "p1").set_goal("建设可在断网时安全运行的系统")
    graph = repository.load_graph("p1")
    system = graph.entity_index[first["system"]["id"]]
    requirement = graph.entity_index[first["requirement"]["id"]]

    assert system.kind is EntityKind.SYSTEM
    assert system.payload["mission"] == "建设可在断网时安全运行的系统"
    assert requirement.payload["source"] == "user_goal"
    assert any(
        relation.source_id == requirement.id
        and relation.target_id == system.id
        and relation.predicate.value == "derivedFrom"
        for relation in graph.relations
    )

    second = ProjectContextService(repository, "p1").set_goal("建设可在断网时安全运行的系统")
    assert second["created"] is False
    assert repository.load_graph("p1").revision == 1


def test_project_goal_adds_a_second_goal_without_erasing_first(tmp_path: Path):
    root = tmp_path / "workspaces"
    create_managed_workspace(root, "p1")
    repository = SQLiteModelRepository(root / "p1" / ".rflp" / "model.db")
    repository.ensure_project("p1")
    service = ProjectContextService(repository, "p1")

    service.set_goal("完成任务")
    service.set_goal("支持人工接管")

    system = next(item for item in repository.load_graph("p1").entities if item.kind is EntityKind.SYSTEM)
    assert system.payload["user_goals"] == ["完成任务", "支持人工接管"]
    assert len([item for item in repository.load_graph("p1").entities if item.kind is EntityKind.REQUIREMENT]) == 2
