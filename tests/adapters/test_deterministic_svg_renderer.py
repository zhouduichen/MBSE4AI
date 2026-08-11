from rflp_lite.adapters.deterministic_svg_renderer import DeterministicSvgRenderer
from rflp_lite.domain.diagram_spec import DiagramEdge, DiagramNode, DiagramSpec


def spec():
    return DiagramSpec.create(diagram_type="environment", title="环境 <图>", source_graph_hash="graph-1", groups=(), nodes=(DiagramNode("system", "飞行汽车", "system_boundary", "accepted"), DiagramNode("doctor", "急救医生", "stakeholder", "accepted")), edges=(DiagramEdge("edge-1", "doctor", "system", "interactsWith", "提交任务"),))


def test_svg_is_stable_escaped_and_contains_traceable_ids():
    renderer = DeterministicSvgRenderer()
    first = renderer.render(spec())
    second = renderer.render(spec())
    assert first == second
    assert first.content_type == "image/svg+xml"
    assert "环境 &lt;图&gt;" in first.content.decode("utf-8")
    assert "环境 <图>" not in first.content.decode("utf-8")
    assert b'data-source-id="doctor"' in first.content
    assert b'marker-end="url(#arrow)"' in first.content


def test_svg_never_renders_nonaccepted_node_status():
    invalid = DiagramSpec.create(diagram_type="environment", title="非法", source_graph_hash="graph-1", groups=(), nodes=(DiagramNode("draft", "草稿", "stakeholder", "candidate"),), edges=())
    try:
        DeterministicSvgRenderer().render(invalid)
    except ValueError as exc:
        assert "accepted" in str(exc)
    else:
        raise AssertionError("candidate node was rendered")
