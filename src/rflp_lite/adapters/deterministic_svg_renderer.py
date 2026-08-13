"""Small dependency-free SVG renderer with stable output."""

from __future__ import annotations

from html import escape

from rflp_lite.domain.diagram_spec import DiagramSpec
from rflp_lite.ports.diagram_renderer import RenderedDiagram


LAYOUT_BY_TYPE = {
    "stakeholder_hierarchy": "hierarchy", "environment": "network", "requirements": "hierarchy", "lifecycle": "state", "operational_decomposition": "hierarchy", "operational_sequence": "sequence", "functional_decomposition": "hierarchy", "functional_interaction": "network", "functional_sequence": "sequence", "logical_decomposition": "hierarchy", "logical_interaction": "network", "physical_allocation": "layers", "physical_interaction": "network", "technical_requirements": "hierarchy", "traceability": "layers",
}


def _label(value: object, limit: int = 60) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


class DeterministicSvgRenderer:
    width = 1200
    margin = 36
    header = 72
    node_width = 220
    node_height = 64

    def render(self, spec: DiagramSpec) -> RenderedDiagram:
        if any(node.status != "accepted" for node in spec.nodes):
            raise ValueError("only accepted diagram nodes can be rendered")
        nodes = sorted(spec.nodes, key=lambda node: (node.group_id, node.order, node.kind, node.label, node.source_id))
        positions = {}
        mode = LAYOUT_BY_TYPE.get(spec.diagram_type, "network")
        for index, node in enumerate(nodes):
            if mode == "sequence":
                x = self.margin + index * (self.node_width + 36)
                y = self.header + 36
            else:
                column = index % 4
                row = index // 4
                x = self.margin + column * (self.node_width + 36)
                y = self.header + 44 + row * (self.node_height + 38)
            positions[node.source_id] = (x, y)
        rows = max(1, (len(nodes) + 3) // 4)
        height = self.header + 44 + rows * (self.node_height + 38) + self.margin
        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{height}" viewBox="0 0 {self.width} {height}">', '<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L9,3 z" fill="#52606d"/></marker></defs>', '<rect width="100%" height="100%" fill="#f7f9fb"/>']
        parts.append(f'<text x="{self.margin}" y="42" font-family="Arial, sans-serif" font-size="24" font-weight="700" fill="#152536"><title>{escape(spec.title, quote=True)}</title>{escape(_label(spec.title, 80), quote=True)}</text>')
        for group in sorted(spec.groups, key=lambda value: (value.order, value.id)):
            group_nodes = [node for node in nodes if node.group_id == group.id and node.source_id in positions]
            if not group_nodes:
                continue
            xs = [positions[node.source_id][0] for node in group_nodes]
            ys = [positions[node.source_id][1] for node in group_nodes]
            x = min(xs) - 14
            y = min(ys) - 28
            w = max(xs) - min(xs) + self.node_width + 28
            h = max(ys) - min(ys) + self.node_height + 42
            parts.append(f'<g data-group-id="{escape(group.id, quote=True)}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="#e9f0f6" stroke="#c4d2de"/><text x="{x + 12}" y="{y + 20}" font-family="Arial, sans-serif" font-size="13" fill="#52606d">{escape(_label(group.label, 60), quote=True)}</text></g>')
        for edge in sorted(spec.edges, key=lambda value: (value.order, value.id)):
            if edge.source_id not in positions or edge.target_id not in positions:
                continue
            sx, sy = positions[edge.source_id]
            tx, ty = positions[edge.target_id]
            x1, y1 = sx + self.node_width / 2, sy + self.node_height / 2
            x2, y2 = tx + self.node_width / 2, ty + self.node_height / 2
            dash = ' stroke-dasharray="6 4"' if edge.predicate == "reply" else ""
            label = escape(_label(edge.label or edge.predicate, 60), quote=True)
            parts.append(f'<g data-edge-id="{escape(edge.id, quote=True)}"><path d="M{x1:g},{y1:g} L{x2:g},{y2:g}" fill="none" stroke="#52606d" stroke-width="2"{dash} marker-end="url(#arrow)"/><text x="{(x1+x2)/2:g}" y="{(y1+y2)/2-6:g}" font-family="Arial, sans-serif" font-size="11" fill="#52606d">{label}</text></g>')
        for node in nodes:
            x, y = positions[node.source_id]
            fill = "#ffffff" if node.kind != "system_boundary" else "#dcecff"
            parts.append(f'<g data-source-id="{escape(node.source_id, quote=True)}"><title>{escape(str(node.label), quote=True)}</title><rect x="{x}" y="{y}" width="{self.node_width}" height="{self.node_height}" rx="10" fill="{fill}" stroke="#6b7c8e"/><text x="{x+12}" y="{y+27}" font-family="Arial, sans-serif" font-size="14" font-weight="600" fill="#152536">{escape(_label(node.label), quote=True)}</text><text x="{x+12}" y="{y+47}" font-family="Arial, sans-serif" font-size="11" fill="#52606d">{escape(_label(node.detail or node.kind, 32), quote=True)}</text></g>')
        parts.append("</svg>")
        return RenderedDiagram(diagram_id=spec.id, content_type="image/svg+xml", extension="svg", content="".join(parts).encode("utf-8"), warnings=spec.warnings)
