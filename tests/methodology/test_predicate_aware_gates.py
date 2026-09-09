from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.gates import functional_gate, global_gate, rflp_gate


def test_wrong_predicate_cannot_pass_function_gate():
    requirement = make_entity(EntityKind.REQUIREMENT, "需求", {"obligation": "支持配送"}, status=EntityStatus.ACCEPTED)
    function = make_entity(EntityKind.FUNCTION, "支持配送")
    graph = ModelGraph("p1", (requirement, function), (Relation("r1", requirement.id, RelationPredicate.CONNECTED_TO, function.id),))

    result = functional_gate(graph)

    assert result.passed is False
    assert result.checks[0]["missing_stage"] == "function"
    assert result.checks[0]["expected_predicates"] == ["satisfiedBy"]


def test_global_gate_requires_verified_by():
    requirement = make_entity(EntityKind.REQUIREMENT, "需求", {"obligation": "支持配送"}, status=EntityStatus.ACCEPTED)
    verification = make_entity(EntityKind.VERIFICATION_CASE, "验证", {"method": "test", "pass_criteria": "通过"})
    graph = ModelGraph("p1", (requirement, verification), (Relation("r1", requirement.id, RelationPredicate.SUPPORTED_BY, verification.id),))

    result = global_gate(graph)

    assert result.passed is False
    assert result.issues[0].code == "broken_requirement_verification_trace"
