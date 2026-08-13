import pytest

from rflp_lite.domain.diagram_spec import DiagramEdge, DiagramGroup, DiagramNode, DiagramSpec


def test_diagram_spec_is_deterministic_and_keeps_source_ids():
    spec = DiagramSpec.create(diagram_type="environment", title="系统环境图", source_graph_hash="graph-1", groups=(DiagramGroup("system", "目标系统", 0),), nodes=(DiagramNode("s1", "飞行汽车", "system_boundary", "accepted", "system"),), edges=())
    assert spec.id.startswith("diagram-")
    assert spec.as_dict()["nodes"][0]["source_id"] == "s1"


def test_diagram_spec_rejects_duplicate_ids_and_dangling_edges():
    node = DiagramNode("s1", "系统", "system", "accepted")
    with pytest.raises(ValueError, match="unique"):
        DiagramSpec.create(diagram_type="environment", title="坏图", source_graph_hash="g", groups=(), nodes=(node, node), edges=())
    with pytest.raises(ValueError, match="reference"):
        DiagramSpec.create(diagram_type="environment", title="坏图", source_graph_hash="g", groups=(), nodes=(node,), edges=(DiagramEdge("e1", "s1", "missing", "flow"),))
