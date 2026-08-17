"""Deterministic fallback rendering for professional semantic MBSE views."""

from __future__ import annotations

from html import escape

from rflp_lite.adapters.graphviz_engine import GraphvizEngine
from rflp_lite.adapters.matrix_engine import MatrixEngine
from rflp_lite.adapters.plantuml_engine import PlantUMLEngine
from rflp_lite.application.mbse_exchange import validate_mbse_model
from rflp_lite.application.mbse_matrix import render_matrix_view
from rflp_lite.application.mbse_views import (
    compile_mbse_view,
    semantic_model_for_view,
    view_definition,
)
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.application.sequence_layout import layout_sequence
from rflp_lite.application.sequence_modeling import _legacy_model_to_interaction
from rflp_lite.application.sequence_render import render_sequence_svg


def _fallback_graph_svg(compiled: dict[str, object]) -> str:
    nodes = [item for item in compiled.get("nodes", ()) if isinstance(item, dict)]
    edges = [item for item in compiled.get("edges", ()) if isinstance(item, dict)]
    layout = str(compiled.get("layout", "flow"))
    width = 1180
    columns = 3 if layout == "tree" else max(1, min(4, len(nodes)))
    node_width = 260
    node_height = 68
    gap_x = 34
    gap_y = 42
    start_x = 36
    start_y = 102
    positions: dict[str, tuple[int, int]] = {}
    for index, item in enumerate(nodes):
        if layout == "flow":
            x = start_x + (index % max(columns, 1)) * (node_width + gap_x)
            y = start_y + (index // max(columns, 1)) * (node_height + gap_y)
        elif layout == "radial":
            x = start_x + (index % 4) * (node_width + gap_x)
            y = start_y + (index // 4) * (node_height + gap_y)
        else:
            x = start_x + (index % columns) * (node_width + gap_x)
            y = start_y + (index // columns) * (node_height + gap_y)
        positions[str(item.get("id"))] = (x, y)
    rows = max(1, (len(nodes) + columns - 1) // columns)
    height = max(240, start_y + rows * (node_height + gap_y) + 80)
    marker_id = f"arrow-{str(compiled.get('view_id', 'mbse')).replace('_', '-') }"
    parts = [
        f'<svg class="mbse-professional-svg" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(str(compiled.get("title", "MBSE 视图")))}" xmlns="http://www.w3.org/2000/svg">',
        f'<defs><marker id="{marker_id}" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#64748b"/></marker></defs>',
        '<rect width="100%" height="100%" fill="#ffffff" stroke="#cbd5e1"/>',
        f'<text x="36" y="38" font-family="Arial" font-size="22" font-weight="700" fill="#0f172a">{escape(str(compiled.get("title", "MBSE 视图")))}</text>',
        f'<text x="36" y="64" font-family="Arial" font-size="12" fill="#64748b">布局：{escape(str(compiled.get("layout", "flow")))} · 节点：{len(nodes)} · 关系：{len(edges)}</text>',
    ]
    for edge in edges:
        source = positions.get(str(edge.get("source_id")))
        target = positions.get(str(edge.get("target_id")))
        if source is None or target is None:
            continue
        sx = source[0] + node_width / 2
        sy = source[1] + node_height
        tx = target[0] + node_width / 2
        ty = target[1]
        parts.append(
            f'<path d="M {sx:.1f} {sy:.1f} L {tx:.1f} {ty:.1f}" fill="none" stroke="#94a3b8" stroke-width="1.6" marker-end="url(#{marker_id})"/>'
        )
        if edge.get("kind"):
            parts.append(
                f'<text x="{(sx + tx) / 2:.1f}" y="{(sy + ty) / 2 - 4:.1f}" font-family="Arial" font-size="10" fill="#475569">{escape(str(edge.get("kind")))}</text>'
            )
    for item in nodes:
        x, y = positions[str(item.get("id"))]
        fill = "#fff7ed" if item.get("needs_analysis") else "#f8fafc"
        stroke = "#f59e0b" if item.get("needs_analysis") else "#64748b"
        parts.append(f'<rect x="{x}" y="{y}" width="{node_width}" height="{node_height}" rx="12" fill="{fill}" stroke="{stroke}" stroke-width="1.4"/>')
        parts.append(f'<text x="{x + 14}" y="{y + 25}" font-family="Arial" font-size="13" font-weight="700" fill="#0f172a">{escape(str(item.get("name", item.get("id", "")))[:34])}</text>')
        parts.append(f'<text x="{x + 14}" y="{y + 46}" font-family="Arial" font-size="10" fill="#64748b">{escape(str(item.get("kind", "")))} · {escape(str(item.get("status", "accepted")))}</text>')
    parts.append("</svg>")
    return "".join(parts)


def render_mbse_svg(model: object, view: str = "all") -> str:
    normalized = validate_mbse_model(model)
    if view == "sequence":
        return render_sequence_svg(layout_sequence(_legacy_model_to_interaction(normalized)))
    if view == "use_case":
        view = "use_case_tree"
    elif view == "activity":
        view = "function_tree"
    if view == "all":
        compiled = compile_mbse_view(normalized, "rflp")
        svg = _fallback_graph_svg(compiled)
        # Keep the legacy overview vocabulary visible to existing clients while
        # the new RFLP overview carries the richer semantic graph.
        return svg.replace(
            "</svg>",
            '<text x="36" y="88" font-family="Arial" font-size="11" fill="#475569">Use Case · Activity · Sequence · Requirement → Function → Logical → Physical</text></svg>',
        )
    if view in {"allocation_matrix", "traceability_matrix"}:
        return render_matrix_view(normalized, view)
    compiled = compile_mbse_view(normalized, view)
    return _fallback_graph_svg(compiled)


def compile_mbse_source(model: object, view: str = "all") -> dict[str, object]:
    """Return DOT/PlantUML/matrix metadata for optional professional engines."""

    normalized = validate_mbse_model(model)
    if view == "all":
        view = "rflp"
    return compile_mbse_view(normalized, view)


def select_diagram_engine(view_id: str, requested_engine: str | None = None):
    definition = view_definition("rflp" if view_id == "all" else view_id)
    requested = str(requested_engine or "auto").strip().lower()
    if requested in {"", "auto"}:
        requested = definition.compiler
    if requested == "fallback":
        return None
    if requested == "graphviz":
        return GraphvizEngine()
    if requested == "plantuml":
        return PlantUMLEngine()
    if requested == "matrix":
        return MatrixEngine()
    raise ContractViolation(f"unsupported diagram engine: {requested}")


def render_mbse_view(
    model: object,
    view: str = "all",
    *,
    engine: str | None = None,
    output_format: str = "svg",
    timeout_seconds: int = 10,
) -> dict[str, object]:
    """Render through an optional engine and always retain a deterministic fallback."""

    normalized = validate_mbse_model(model)
    view_id = "rflp" if view == "all" else view
    compiled = compile_mbse_source(normalized, view_id)
    selected = select_diagram_engine(view_id, engine)
    if selected is None:
        fallback = render_mbse_svg(normalized, view)
        return {
            "content": fallback.encode("utf-8"),
            "media_type": "image/svg+xml",
            "engine_id": "fallback",
            "requested_engine": engine or "fallback",
            "fallback": True,
            "diagnostic": "使用内置确定性 SVG",
            "source": compiled["source"],
            "view_id": view_id,
        }
    source = str(compiled.get("source", ""))
    if compiled.get("compiler") == "matrix":
        source = render_matrix_view(normalized, view_id)
    result = selected.render(source, output_format, timeout_seconds)
    if result.success:
        return {
            "content": result.content,
            "media_type": result.media_type,
            "engine_id": result.engine_id,
            "requested_engine": engine or "auto",
            "fallback": False,
            "diagnostic": result.diagnostic,
            "source": source,
            "view_id": view_id,
        }
    fallback = render_mbse_svg(normalized, view)
    return {
        "content": fallback.encode("utf-8"),
        "media_type": "image/svg+xml",
        "engine_id": "fallback",
        "requested_engine": engine or "auto",
        "fallback": True,
        "diagnostic": result.diagnostic,
        "source": source,
        "view_id": view_id,
    }
