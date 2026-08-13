from rflp_lite.application.diagrams.service import DiagramService
from rflp_lite.ports.diagram_renderer import RenderedDiagram


class RecordingRenderer:
    def __init__(self): self.types = []
    def render(self, spec):
        self.types.append(spec.diagram_type)
        return RenderedDiagram(spec.id, "image/svg+xml", "svg", f"<svg>{spec.diagram_type}</svg>".encode("utf-8"))


def test_diagram_service_builds_then_renders_without_model_calls():
    renderer = RecordingRenderer()
    graph = {"graph_hash": "graph-1", "elements": [{"id": "system", "kind": "system_boundary", "name": "飞行汽车", "status": "accepted", "attributes": {}}], "relations": []}
    results = DiagramService(renderer).render_all(graph, {"diagram_groups": {}})
    assert results and renderer.types and all(item.content.startswith(b"<svg>") for item in results)
