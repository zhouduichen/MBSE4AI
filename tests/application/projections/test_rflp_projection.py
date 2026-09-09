from rflp_lite.application.projections.rflp import build_rflp_view
from rflp_lite.diagrams.engineering.rflp import render_rflp_svg
from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate


def test_rflp_projection_keeps_invalid_edge_but_never_marks_it_valid():
    requirement = make_entity(EntityKind.REQUIREMENT, "R", status=EntityStatus.ACCEPTED)
    function = make_entity(EntityKind.FUNCTION, "F")
    graph = ModelGraph("p1", (requirement, function), (Relation("invalid", requirement.id, RelationPredicate.DERIVED_FROM, function.id),))
    view = build_rflp_view(graph)
    assert view["edges"][0]["valid_for_trace"] is False
    assert view["gaps"][0]["missing"]
    assert "invalid" in render_rflp_svg(view)


def test_rflp_focus_is_stable_for_complete_path():
    requirement = make_entity(EntityKind.REQUIREMENT, "R", status=EntityStatus.ACCEPTED)
    function = make_entity(EntityKind.FUNCTION, "F")
    logical = make_entity(EntityKind.LOGICAL_COMPONENT, "L")
    physical = make_entity(EntityKind.PHYSICAL_BLOCK, "P")
    relations = (Relation("rf", requirement.id, RelationPredicate.SATISFIED_BY, function.id), Relation("fl", function.id, RelationPredicate.ALLOCATED_TO, logical.id), Relation("lp", logical.id, RelationPredicate.ALLOCATED_TO, physical.id))
    view = build_rflp_view(ModelGraph("p1", (requirement, function, logical, physical), relations), selected_requirement=requirement.id)
    assert view["selected_trace"] == [requirement.id, function.id, logical.id, physical.id]
    assert all(item["focused"] for item in view["nodes"])
