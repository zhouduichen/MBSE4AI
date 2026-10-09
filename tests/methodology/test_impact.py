import pytest

from rflp_lite.domain.entities import Entity, EntityKind, EntityStatus, make_entity
from rflp_lite.domain.errors import NotFoundError
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.impact import TypedImpactPlanner


def _rflp_graph() -> tuple[ModelGraph, dict[str, Entity]]:
    requirement = make_entity(
        EntityKind.REQUIREMENT, "续航约束", status=EntityStatus.VALIDATED
    )
    function = make_entity(
        EntityKind.FUNCTION, "管理能量", status=EntityStatus.VALIDATED
    )
    logical = make_entity(
        EntityKind.LOGICAL_COMPONENT, "能量控制器", status=EntityStatus.VALIDATED
    )
    physical = make_entity(
        EntityKind.PHYSICAL_BLOCK, "计算平台", status=EntityStatus.VALIDATED
    )
    verification = make_entity(
        EntityKind.VERIFICATION_CASE, "验证续航", status=EntityStatus.VALIDATED
    )
    validation = make_entity(
        EntityKind.VALIDATION_CASE, "确认任务续航", status=EntityStatus.VALIDATED
    )
    disconnected = make_entity(
        EntityKind.FUNCTION, "无关功能", status=EntityStatus.VALIDATED
    )
    graph = ModelGraph(
        "p1",
        (requirement, function, logical, physical, verification, validation, disconnected),
        (
            Relation("r-f", requirement.id, RelationPredicate.SATISFIED_BY, function.id),
            Relation("f-l", function.id, RelationPredicate.ALLOCATED_TO, logical.id),
            Relation("l-p", logical.id, RelationPredicate.ALLOCATED_TO, physical.id),
            Relation("r-v", requirement.id, RelationPredicate.VERIFIED_BY, verification.id),
            Relation("r-va", requirement.id, RelationPredicate.VALIDATED_BY, validation.id),
        ),
        revision=7,
    )
    return graph, {
        "requirement": requirement,
        "function": function,
        "logical": logical,
        "physical": physical,
        "verification": verification,
        "validation": validation,
        "disconnected": disconnected,
    }


def test_requirement_impact_follows_typed_rflp_and_vv_edges_but_not_disconnected_nodes():
    graph, entities = _rflp_graph()

    plan = TypedImpactPlanner().plan(graph, (entities["requirement"].id,))

    assert set(plan.impacted_entity_ids) == {
        entities["requirement"].id,
        entities["function"].id,
        entities["logical"].id,
        entities["physical"].id,
        entities["verification"].id,
        entities["validation"].id,
    }
    assert entities["disconnected"].id not in plan.impacted_entity_ids
    assert plan.selected_stages == (
        "requirements",
        "functional",
        "logical",
        "physical",
        "verification_validation",
    )
    assert plan.verification_case_ids == (entities["verification"].id,)
    assert plan.validation_case_ids == (entities["validation"].id,)
    assert any("satisfiedBy" in path.predicates for path in plan.impact_paths)


def test_function_and_physical_changes_start_at_their_earliest_vertical_stage():
    graph, entities = _rflp_graph()

    function_plan = TypedImpactPlanner().plan(graph, (entities["function"].id,))
    physical_plan = TypedImpactPlanner().plan(graph, (entities["physical"].id,))

    assert function_plan.selected_stages == (
        "functional", "logical", "physical", "verification_validation"
    )
    assert physical_plan.selected_stages == ("physical", "verification_validation")
    assert entities["requirement"].id in physical_plan.impacted_entity_ids
    assert entities["validation"].id in physical_plan.validation_case_ids


def test_unknown_seed_is_rejected_and_paths_are_bounded():
    graph, entities = _rflp_graph()
    planner = TypedImpactPlanner()

    with pytest.raises(NotFoundError):
        planner.plan(graph, ("missing-entity",))

    bounded = planner.plan(
        graph,
        (entities["requirement"].id,),
        max_entities=3,
        max_paths=1,
    )
    assert len(bounded.impacted_entity_ids) <= 3
    assert len(bounded.impact_paths) <= 1
    assert bounded.revision == graph.revision
    assert bounded.snapshot_hash == graph.snapshot_hash


def test_deprecated_entities_are_not_included_in_impact():
    graph, entities = _rflp_graph()
    deprecated = make_entity(
        EntityKind.FUNCTION, "已淘汰功能", status=EntityStatus.DEPRECATED
    )
    graph = ModelGraph(
        graph.project_id,
        (*graph.entities, deprecated),
        (*graph.relations, Relation(
            "r-deprecated", entities["requirement"].id,
            RelationPredicate.SATISFIED_BY, deprecated.id,
        )),
        graph.revision,
    )

    plan = TypedImpactPlanner().plan(graph, (entities["requirement"].id,))

    assert deprecated.id not in plan.impacted_entity_ids
