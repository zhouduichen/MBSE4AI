from rflp_lite.application.projections.assurance import build_assurance_view
from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate


def test_assurance_projection_does_not_fabricate_verification_or_hazard_facts():
    requirement = make_entity(EntityKind.REQUIREMENT, "R", status=EntityStatus.ACCEPTED)
    hazard = make_entity(EntityKind.HAZARD, "Overheating")
    graph = ModelGraph("p1", (requirement, hazard), (Relation("cause", hazard.id, RelationPredicate.CAUSES, requirement.id),))
    view = build_assurance_view(graph)
    assert view["verification_validation"][0]["status"] == "MISSING_VERIFICATION"
    assert view["hazards"][0]["name"] == "Overheating"
    assert view["hazards"][0]["mitigations"] == []
