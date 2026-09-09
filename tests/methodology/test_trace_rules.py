from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.trace_rules import R_TO_F, R_TO_V, rflp_paths, targets


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
