"""Stable SVG renderer for the RFLP projection."""

from __future__ import annotations

from html import escape
from typing import Mapping


_LANES = ("requirement", "function", "logical_component", "physical_block")
_LABELS = {"requirement": "Requirement", "function": "Function", "logical_component": "Logical", "physical_block": "Physical"}
_COLORS = {"requirement": "#1d4ed8", "function": "#0f766e", "logical_component": "#7c3aed", "physical_block": "#b45309"}


def render_rflp_svg(view: Mapping[str, object]) -> str:
    nodes = list(view.get("nodes", ()))
    edges = list(view.get("edges", ()))
    by_id = {str(node["id"]): node for node in nodes}
    columns: dict[str, list[Mapping[str, object]]] = {lane: [] for lane in _LANES}
    for node in nodes:
        columns.setdefault(str(node.get("kind", "")), []).append(node)
    max_rows = max((len(items) for items in columns.values()), default=0)
    width, height = 1160, max(180, 96 + max_rows * 88)
    positions: dict[str, tuple[int, int]] = {}
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="RFLP architecture trace" viewBox="0 0 {width} {height}" width="{width}" height="{height}">', '<style>.rflp-label{font:600 11px Arial}.rflp-kind{font:10px Arial}.rflp-edge{font:9px Arial}.muted{opacity:.22}.invalid{stroke-dasharray:5 4}</style>']
    for index, lane in enumerate(_LANES):
        x = 22 + index * 282
        parts.append(f'<text x="{x}" y="24" class="rflp-label" fill="{_COLORS[lane]}">{_LABELS[lane]}</text>')
        parts.append(f'<line x1="{x}" y1="32" x2="{x + 232}" y2="32" stroke="#d9dee7"/>')
        for row, node in enumerate(columns.get(lane, ())):
            node_id = str(node["id"])
            y = 48 + row * 88
            positions[node_id] = (x, y)
            opacity = "" if bool(node.get("focused", True)) else " muted"
            fill = "#fff" if bool(node.get("focused", True)) else "#f3f4f6"
            label = escape(str(node.get("label", node.get("name", node_id)))[:34])
            parts.append(f'<g class="{opacity.strip()}"><rect x="{x}" y="{y}" width="232" height="58" rx="5" fill="{fill}" stroke="{_COLORS[lane]}"/><text x="{x + 10}" y="{y + 21}" class="rflp-label">{label}</text><text x="{x + 10}" y="{y + 40}" class="rflp-kind" fill="#596273">{escape(node_id)} · {escape(str(node.get("status", "")))}</text></g>')
    for edge in edges:
        start, end = positions.get(str(edge.get("source"))), positions.get(str(edge.get("target")))
        if not start or not end:
            continue
        focused = bool(edge.get("focused", True))
        invalid = not bool(edge.get("valid_for_trace", False))
        cls = ("" if focused else " muted") + (" invalid" if invalid else "")
        x1, y1 = start[0] + 232, start[1] + 29
        x2, y2 = end[0], end[1] + 29
        parts.append(f'<path class="{cls.strip()}" d="M{x1},{y1} L{x2},{y2}" stroke="#64748b" fill="none" marker-end="url(#arrow)"/>')
        parts.append(f'<text x="{(x1 + x2) // 2 - 22}" y="{(y1 + y2) // 2 - 5}" class="rflp-edge">{escape(str(edge.get("predicate", "")))}</text>')
    for gap_index, gap in enumerate(view.get("gaps", ())):
        x, y = 22 + 4 * 282, 48 + gap_index * 58
        parts.append(f'<g><rect x="{x}" y="{y}" width="220" height="40" rx="5" fill="#fff7ed" stroke="#c2410c" stroke-dasharray="4 3"/><text x="{x + 8}" y="{y + 17}" class="rflp-label" fill="#9a3412">Missing trace</text><text x="{x + 8}" y="{y + 32}" class="rflp-kind">{escape(str(gap.get("requirement_id", "")))}: {escape(", ".join(str(item) for item in gap.get("missing", ())))}</text></g>')
    parts.insert(1, '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#64748b"/></marker></defs>')
    parts.append("</svg>")
    return "".join(parts)
