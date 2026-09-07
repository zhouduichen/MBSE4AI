"""Dependency-light renderers for typed view specifications."""

from __future__ import annotations

import json
from html import escape

from rflp_lite.diagrams.views import ViewSpec


def render_json(view: ViewSpec) -> bytes:
    return (json.dumps(view.as_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def render_dot(view: ViewSpec) -> bytes:
    lines = ["digraph ModelGraph {", '  graph [rankdir="LR"];', '  node [shape="box"];']
    for node in view.nodes:
        lines.append(f'  "{escape(str(node["id"]))}" [label="{escape(str(node["name"]))}"];')
    for edge in view.edges:
        lines.append(
            f'  "{escape(str(edge["source_id"]))}" -> "{escape(str(edge["target_id"]))}" [label="{escape(str(edge["predicate"]))}"];'
        )
    lines.append("}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def render_svg(view: ViewSpec) -> bytes:
    width = 1200
    height = max(180, 100 + 90 * ((len(view.nodes) + 4) // 5))
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        f'<text x="24" y="34" font-family="Arial" font-size="22" font-weight="700">{escape(view.title)}</text>',
    ]
    positions: dict[str, tuple[int, int]] = {}
    for index, node in enumerate(view.nodes):
        x = 24 + (index % 5) * 235
        y = 60 + (index // 5) * 90
        node_id = str(node["id"])
        positions[node_id] = (x, y)
        parts.append(f'<rect x="{x}" y="{y}" width="205" height="56" rx="8" fill="#f8fafc" stroke="#64748b"/>')
        parts.append(f'<text x="{x + 10}" y="{y + 24}" font-family="Arial" font-size="13">{escape(str(node["name"])[:28])}</text>')
        parts.append(f'<text x="{x + 10}" y="{y + 43}" font-family="Arial" font-size="10" fill="#475569">{escape(str(node["kind"]))}</text>')
    for edge in view.edges:
        start = positions.get(str(edge["source_id"]))
        end = positions.get(str(edge["target_id"]))
        if start and end:
            parts.append(f'<path d="M{start[0] + 205},{start[1] + 28} L{end[0]},{end[1] + 28}" stroke="#64748b" fill="none"/>')
    parts.append("</svg>")
    return "".join(parts).encode("utf-8")


def render_view(view: ViewSpec, output_format: str = "json") -> tuple[bytes, str]:
    if output_format == "json":
        return render_json(view), "application/json"
    if output_format == "dot":
        return render_dot(view), "text/vnd.graphviz"
    if output_format == "svg":
        return render_svg(view), "image/svg+xml"
    raise ValueError(f"unsupported view format: {output_format}")
