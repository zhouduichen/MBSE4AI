from rflp_lite.application.projections.requirements import build_requirement_detail, build_requirements_view
from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.model import ModelGraph


def test_requirements_projection_is_deterministic_and_keeps_large_candidate_sets():
    requirements = tuple(make_entity(EntityKind.REQUIREMENT, f"Requirement {index}", {"statement": f"System shall satisfy {index}"}) for index in range(120))
    graph = ModelGraph("synthetic", requirements, (), 7)
    first = build_requirements_view(graph, ())
    second = build_requirements_view(graph, ())
    assert first == second
    assert len(first["rows"]) == 120
    assert first["metrics"]["candidate_count"] == 120
    assert first["rows"][0]["id"] == sorted(item.id for item in requirements)[0]


def test_requirement_detail_preserves_trace_ids_and_source_evidence():
    requirement = make_entity(EntityKind.REQUIREMENT, "Battery endurance", {"statement": "Battery shall last 8 hours"}, source_ids=("doc-1",), evidence_ids=("evidence-1",), status=EntityStatus.ACCEPTED)
    function = make_entity(EntityKind.FUNCTION, "Manage energy")
    graph = ModelGraph("p1", (requirement, function), ())
    detail = build_requirement_detail(graph, requirement.id, evidence=({"id": "evidence-1", "claim": "8 hours"},))
    assert detail is not None
    assert detail["sources"] == ({"id": "doc-1", "reference": "doc-1"},)
    assert detail["evidence"][0]["claim"] == "8 hours"
    assert detail["trace_path"] == (requirement.id,)
