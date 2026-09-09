from rflp_lite.application.projections.traceability import build_traceability_view
from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate


def test_traceability_marks_invalid_predicate_and_missing_stages():
    requirement = make_entity(EntityKind.REQUIREMENT, "Control response", status=EntityStatus.ACCEPTED)
    function = make_entity(EntityKind.FUNCTION, "Control")
    graph = ModelGraph("p1", (requirement, function), (Relation("bad", requirement.id, RelationPredicate.DERIVED_FROM, function.id),))
    view = build_traceability_view(graph)
    assert view["rows"][0]["status"] == "INVALID_PREDICATE"
    assert "invalid_predicate" in view["rows"][0]["gaps"]


def test_traceability_matrix_has_a_row_for_candidate_requirements():
    requirements = tuple(make_entity(EntityKind.REQUIREMENT, f"R{index}") for index in range(3))
    view = build_traceability_view(ModelGraph("p1", requirements, ()))
    assert [item["requirement_id"] for item in view["rows"]] == sorted(item.id for item in requirements)
    assert all(item["status"] == "BLOCKED" for item in view["rows"])
