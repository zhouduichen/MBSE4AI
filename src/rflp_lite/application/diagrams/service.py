"""Application-level diagram rendering orchestration."""

from __future__ import annotations

from rflp_lite.application.diagrams.specifications import DIAGRAM_TYPES, build_diagram_spec, split_diagram_spec
from rflp_lite.ports.diagram_renderer import DiagramRenderer, RenderedDiagram


class DiagramService:
    def __init__(self, renderer: DiagramRenderer) -> None:
        self.renderer = renderer

    def render_one(self, graph: dict[str, object], pack: dict[str, object], diagram_type: str) -> tuple[RenderedDiagram, ...]:
        spec = build_diagram_spec(graph, diagram_type, pack)
        return tuple(self.renderer.render(page) for page in split_diagram_spec(spec, max_nodes=40))

    def render_all(self, graph: dict[str, object], pack: dict[str, object]) -> tuple[RenderedDiagram, ...]:
        rendered = []
        for diagram_type in DIAGRAM_TYPES:
            spec = build_diagram_spec(graph, diagram_type, pack)
            if not spec.nodes and not spec.edges:
                continue
            rendered.extend(self.renderer.render(page) for page in split_diagram_spec(spec, max_nodes=40))
        return tuple(rendered)
