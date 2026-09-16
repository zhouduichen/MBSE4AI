from pathlib import Path

from rflp_lite.application.requirement_input import RequirementInputService
from rflp_lite.domain.entities import EntityKind, EntityStatus
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.contracts import ContextBundle, Phase, RunStatus
from rflp_lite.methodology.executor import TaskExecutor
from rflp_lite.methodology.tasks import task_catalog
from rflp_lite.methodology.workflow import WorkflowRunner
from rflp_lite.repository.sqlite import SQLiteModelRepository
from rflp_lite.runtime.rule_based import RuleRuntime


def _run_tasks(repository: SQLiteModelRepository, task_ids: tuple[str, ...]) -> None:
    executor = TaskExecutor(RuleRuntime())
    for task in task_catalog():
        if task.id not in task_ids:
            continue
        graph = repository.load_graph("p1")
        context = ContextBundle("p1", task.id, graph.revision, graph.entities, graph.relations)
        response = executor.execute(task, context, token_budget=2000)
        assert response.patch is not None, task.id
        repository.append_patch("p1", response.patch, graph.revision)


def _active_kinds(repository: SQLiteModelRepository) -> set[EntityKind]:
    return {
        item.kind
        for item in repository.load_graph("p1").entities
        if item.meta.status is not EntityStatus.DEPRECATED
    }


def test_operational_and_functional_tasks_create_typed_objects(tmp_path: Path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    RequirementInputService(repository, "p1").ensure_text_requirements(
        "系统应支持自主配送并允许人工接管"
    )

    _run_tasks(repository, tuple(task.id for task in task_catalog()[:14]))

    assert {
        EntityKind.SYSTEM,
        EntityKind.STAKEHOLDER,
        EntityKind.CONCERN,
        EntityKind.LIFECYCLE_STAGE,
        EntityKind.SCENARIO_HYPOTHESIS,
        EntityKind.USE_CASE,
        EntityKind.OPERATIONAL_SCENARIO,
        EntityKind.ACTIVITY,
        EntityKind.REQUIREMENT,
        EntityKind.FUNCTION,
        EntityKind.FUNCTIONAL_FLOW,
        EntityKind.FUNCTIONAL_SCENARIO,
    } <= _active_kinds(repository)

    graph = repository.load_graph("p1")
    use_case = next(item for item in graph.entities if item.kind is EntityKind.USE_CASE)
    activity = next(item for item in graph.entities if item.kind is EntityKind.ACTIVITY)
    requirements = [
        item for item in graph.entities
        if item.kind is EntityKind.REQUIREMENT
        and str(item.payload.get("level", "")).lower() != "technical"
    ]
    assert set(activity.payload["branch_types"]) == {
        "normal", "failure", "alternative", "boundary", "exception",
    }
    assert activity.payload["use_case_ids"] == [use_case.id]
    assert all(
        any(
            relation.source_id == requirement.id
            and relation.target_id == use_case.id
            and relation.predicate is RelationPredicate.DERIVED_FROM
            for relation in graph.relations
        )
        for requirement in requirements
    )
    assert any(
        relation.source_id == use_case.id
        and relation.target_id == activity.id
        and relation.predicate is RelationPredicate.DECOMPOSES
        for relation in graph.relations
    )


def test_lifecycle_fallback_function_name_stays_solution_neutral(tmp_path: Path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    RequirementInputService(repository, "p1").ensure_text_requirements(
        "无人机系统通信链路应稳定，支持高清视频与传感器数据回传"
    )
    runner = WorkflowRunner(repository, repository, RuleRuntime())

    summary = runner.run("p1", force_run=True)

    assert summary.status is RunStatus.COMPLETED
    functions = [
        item for item in repository.load_graph("p1").entities
        if item.kind is EntityKind.FUNCTION
    ]
    assert functions
    assert all("传感器" not in item.meta.name for item in functions)
    assert "传感器" in functions[0].payload["behavior"]


def test_remaining_tasks_create_logical_physical_and_assurance_objects(tmp_path: Path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    RequirementInputService(repository, "p1").ensure_text_requirements(
        "系统功耗不超过 50 W 且续航不少于 10 h"
    )

    _run_tasks(repository, tuple(task.id for task in task_catalog()))

    assert {
        EntityKind.LOGICAL_COMPONENT,
        EntityKind.INTERFACE,
        EntityKind.STATE,
        EntityKind.PHYSICAL_BLOCK,
        EntityKind.HAZARD,
        EntityKind.FAILURE_MODE,
        EntityKind.VERIFICATION_CASE,
        EntityKind.VALIDATION_CASE,
    } <= _active_kinds(repository)

    graph = repository.load_graph("p1")
    logical = next(
        item for item in graph.entities
        if item.kind is EntityKind.LOGICAL_COMPONENT
    )
    logical_reasoning = logical.payload["architecture_reasoning"]
    assert logical_reasoning["basis"]["function_ids"] == [
        logical.payload["function_id"]
    ]
    assert logical_reasoning["alternatives"]
    assert logical_reasoning["selection_status"] == "needs_review"

    physical = next(
        item for item in graph.entities
        if item.kind is EntityKind.PHYSICAL_BLOCK
    )
    physical_reasoning = physical.payload["feasibility_reasoning"]
    assert physical_reasoning["logical_ids"] == [logical.id]
    assert physical_reasoning["propagated_constraints"] == {
        "endurance_h": 10.0,
        "power_w": 50.0,
    }
    assert physical_reasoning["status"] == "needs_measurement"
    assert set(physical_reasoning["missing_fields"]) >= {
        "power_w", "endurance_h", "thermal"
    }


def test_technical_requirement_is_not_invented_without_explicit_fixture_scope(tmp_path: Path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    RequirementInputService(repository, "p1").ensure_text_requirements(
        "系统应支持自主配送并允许人工接管"
    )

    _run_tasks(repository, tuple(task.id for task in task_catalog()))

    graph = repository.load_graph("p1")
    technical = [
        item for item in graph.entities
        if item.kind is EntityKind.REQUIREMENT
        and item.payload.get("level") == "technical"
    ]
    physicals = [
        item for item in graph.entities
        if item.kind is EntityKind.PHYSICAL_BLOCK
    ]

    assert technical == []
    assert physicals
    assert all(
        item.payload.get("technical_requirement_status") == "no_explicit_constraints"
        for item in physicals
    )
