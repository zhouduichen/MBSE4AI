import pytest

from rflp_lite.application.diagrams.specifications import DIAGRAM_TYPES, build_diagram_spec, split_diagram_spec
from rflp_lite.domain.errors import ContractViolation


def graph():
    return {"graph_hash": "graph-1", "elements": [{"id": "system", "kind": "system_boundary", "name": "飞行汽车", "status": "accepted", "attributes": {}}, {"id": "doctor", "kind": "stakeholder", "name": "急救医生", "status": "accepted", "attributes": {"category": "medical"}}, {"id": "phase", "kind": "lifecycle_phase", "name": "起飞", "status": "accepted", "attributes": {"phase_id": "takeoff"}}, {"id": "function", "kind": "function", "name": "感知障碍物", "status": "accepted", "attributes": {}}, {"id": "draft", "kind": "risk", "name": "未确认", "status": "candidate", "attributes": {}}], "relations": [{"source_id": "doctor", "predicate": "interactsWith", "target_id": "system"}]}


def test_catalog_contains_every_design_diagram_type():
    assert DIAGRAM_TYPES == ("stakeholder_hierarchy", "environment", "requirements", "lifecycle", "operational_decomposition", "operational_sequence", "functional_decomposition", "functional_interaction", "functional_sequence", "logical_decomposition", "logical_interaction", "physical_allocation", "physical_interaction", "technical_requirements", "traceability")


def test_environment_spec_uses_only_accepted_relevant_elements():
    spec = build_diagram_spec(graph(), "environment", {"diagram_groups": {}})
    assert {node.source_id for node in spec.nodes} == {"system", "doctor"}
    assert spec.edges[0].predicate == "interactsWith"


def test_unsupported_type_and_dense_diagram_are_handled_explicitly():
    with pytest.raises(ContractViolation, match="diagram type"):
        build_diagram_spec(graph(), "unknown", {"diagram_groups": {}})
    dense = graph()
    dense["elements"] = [{"id": f"n-{index}", "kind": "stakeholder", "name": f"角色 {index}", "status": "accepted", "attributes": {"category": "medical"}} for index in range(45)]
    spec = build_diagram_spec(dense, "stakeholder_hierarchy", {"diagram_groups": {}})
    pages = split_diagram_spec(spec, max_nodes=40)
    assert len(pages) == 2 and all(len(page.nodes) <= 40 for page in pages)
