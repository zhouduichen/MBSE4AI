from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.trace_rules import (
    R_TO_F, R_TO_V, requirement_lineage, requirement_trace_scope, rflp_paths,
    targets, vv_scope_matches,
)


def _graph(predicate):
    requirement = make_entity(EntityKind.REQUIREMENT, "需求", {"obligation": "支持配送"}, status=EntityStatus.ACCEPTED)
    function = make_entity(EntityKind.FUNCTION, "支持配送")
    verification = make_entity(EntityKind.VERIFICATION_CASE, "验证", {"method": "test", "pass_criteria": "通过"})
    return ModelGraph("p1", (requirement, function, verification), (
        Relation("r1", requirement.id, predicate, function.id),
        Relation("r2", requirement.id, RelationPredicate.VERIFIED_BY, verification.id),
    )), requirement, function


def test_wrong_predicate_is_not_a_requirement_function_trace():
    graph, requirement, _ = _graph(RelationPredicate.CONNECTED_TO)

    assert targets(graph, requirement.id, R_TO_F) == ()
    assert rflp_paths(graph, requirement.id) == ()


def test_verified_by_is_a_distinct_trace_rule():
    graph, requirement, _ = _graph(RelationPredicate.SATISFIED_BY)

    assert targets(graph, requirement.id, R_TO_V)


def test_requirement_lineage_follows_derived_requirement_chain_to_root():
    root = make_entity(EntityKind.REQUIREMENT, "系统需求")
    technical = make_entity(EntityKind.REQUIREMENT, "技术需求", {"level": "technical"})
    nested = make_entity(EntityKind.REQUIREMENT, "候选技术需求", {"level": "technical"})
    graph = ModelGraph(
        "p1",
        (root, technical, nested),
        (
            Relation("technical-root", technical.id, RelationPredicate.DERIVED_FROM, root.id),
            Relation("nested-technical", nested.id, RelationPredicate.DERIVED_FROM, technical.id),
        ),
    )

    assert requirement_lineage(graph, root.id) == (root.id,)
    assert requirement_lineage(graph, technical.id) == (root.id,)
    assert requirement_lineage(graph, nested.id) == (root.id,)


def test_requirement_trace_scope_reuses_root_path_and_direct_technical_physical_link():
    root = make_entity(EntityKind.REQUIREMENT, "系统需求")
    function = make_entity(EntityKind.FUNCTION, "系统功能")
    logical = make_entity(EntityKind.LOGICAL_COMPONENT, "系统逻辑")
    physical = make_entity(EntityKind.PHYSICAL_BLOCK, "系统物理")
    technical = make_entity(
        EntityKind.REQUIREMENT,
        "物理约束",
        {"level": "technical", "source_requirement_ids": [root.id]},
    )
    graph = ModelGraph(
        "p1",
        (root, function, logical, physical, technical),
        (
            Relation("r-f", root.id, RelationPredicate.SATISFIED_BY, function.id),
            Relation("f-l", function.id, RelationPredicate.ALLOCATED_TO, logical.id),
            Relation("l-p", logical.id, RelationPredicate.ALLOCATED_TO, physical.id),
            Relation("t-r", technical.id, RelationPredicate.DERIVED_FROM, root.id),
            Relation("t-p", technical.id, RelationPredicate.SATISFIED_BY, physical.id),
        ),
    )
    scope = requirement_trace_scope(graph, technical.id)
    case = make_entity(
        EntityKind.VERIFICATION_CASE,
        "验证物理约束",
        {**scope.as_dict(), "cross_analysis_status": "checked"},
    )

    assert scope.requirement_ids == (technical.id,)
    assert scope.function_ids == (function.id,)
    assert scope.logical_component_ids == (logical.id,)
    assert scope.physical_ids == (physical.id,)
    assert vv_scope_matches(
        ModelGraph("p1", (*graph.entities, case), graph.relations),
        technical.id,
        case,
    )
    stale = case.__class__(case.meta, {**case.payload, "physical_ids": []})
    assert not vv_scope_matches(
        ModelGraph("p1", (*graph.entities, stale), graph.relations),
        technical.id,
        stale,
    )
