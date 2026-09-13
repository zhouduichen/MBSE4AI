from pathlib import Path

from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.contracts import RunStatus


def test_pipeline_from_natural_language_creates_operational_and_functional_layers(
    tmp_path: Path,
):
    services = build_v2_services(tmp_path / "workspaces")
    services.projects.create("robot")
    services.requirements_input("robot").ensure_text_requirements(
        "系统应支持自主配送并允许人工接管"
    )

    summary = services.analysis("robot").run("robot", force_new=True)

    graph = services.model("robot").graph("robot")
    kinds = {item.kind for item in graph.entities}
    assert {
        EntityKind.SYSTEM,
        EntityKind.STAKEHOLDER,
        EntityKind.CONCERN,
        EntityKind.LIFECYCLE_STAGE,
        EntityKind.SCENARIO_HYPOTHESIS,
        EntityKind.USE_CASE,
        EntityKind.OPERATIONAL_SCENARIO,
        EntityKind.ACTIVITY,
        EntityKind.FUNCTION,
        EntityKind.FUNCTIONAL_FLOW,
        EntityKind.FUNCTIONAL_SCENARIO,
    } <= kinds
    assert summary.status is RunStatus.COMPLETED
    assert len(summary.completed_tasks) == 23


def test_pipeline_closes_logical_physical_and_assurance_layers(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces")
    services.projects.create("robot")
    services.requirements_input("robot").ensure_text_requirements(
        "系统功耗不超过 50 W 且续航不少于 10 h"
    )

    summary = services.analysis("robot").run("robot", force_new=True)
    graph = services.model("robot").graph("robot")
    kinds = {item.kind for item in graph.entities}

    assert {
        EntityKind.LOGICAL_COMPONENT,
        EntityKind.INTERFACE,
        EntityKind.STATE,
        EntityKind.PHYSICAL_BLOCK,
        EntityKind.HAZARD,
        EntityKind.FAILURE_MODE,
        EntityKind.VERIFICATION_CASE,
        EntityKind.VALIDATION_CASE,
    } <= kinds
    assert any(item.payload.get("level") == "technical" for item in graph.entities)
    assert summary.status is RunStatus.COMPLETED
    assert len(summary.completed_tasks) == 23

    requirement = next(
        item for item in graph.entities
        if item.kind is EntityKind.REQUIREMENT
        and item.payload.get("level") != "technical"
    )
    targets = {
        relation.predicate: relation.target_id
        for relation in graph.relations
        if relation.source_id == requirement.id
    }
    function_id = targets[RelationPredicate.SATISFIED_BY]
    logical_id = next(
        relation.target_id
        for relation in graph.relations
        if relation.source_id == function_id
        and relation.predicate is RelationPredicate.ALLOCATED_TO
    )
    physical_id = next(
        relation.target_id
        for relation in graph.relations
        if relation.source_id == logical_id
        and relation.predicate is RelationPredicate.ALLOCATED_TO
    )
    assert physical_id in graph.entity_index
    assert any(
        relation.source_id == requirement.id
        and relation.predicate is RelationPredicate.VERIFIED_BY
        for relation in graph.relations
    )
    assert any(
        relation.source_id == requirement.id
        and relation.predicate is RelationPredicate.VALIDATED_BY
        for relation in graph.relations
    )
