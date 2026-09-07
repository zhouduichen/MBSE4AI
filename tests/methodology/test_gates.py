from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.contracts import Phase
from rflp_lite.methodology.gates import functional_gate, gate_for_phase, operational_gate, rflp_gate


def test_operational_gate_reports_missing_lifecycle():
    graph = ModelGraph("p1", (make_entity(EntityKind.SYSTEM, "系统"),))
    result = operational_gate(graph)
    assert result.passed is False
    assert result.rollback_phase is Phase.OPERATIONAL


def test_functional_gate_passes_with_function():
    graph = ModelGraph("p1", (make_entity(EntityKind.FUNCTION, "配送"),))
    assert functional_gate(graph).passed is True


def test_gate_router_selects_p_gate():
    graph = ModelGraph("p1", (make_entity(EntityKind.REQUIREMENT, "需求"),))
    assert gate_for_phase(Phase.LOGICAL_PHYSICAL, graph).gate_id == "P-Gate"
    assert rflp_gate(graph).passed is False
