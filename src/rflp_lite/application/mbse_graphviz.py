"""Graphviz DOT compiler with MBSE-specific layout policies."""

from __future__ import annotations

from rflp_lite.application.mbse_views import (
    semantic_model_for_view,
    view_definition,
    view_entities,
    view_relations,
)
from rflp_lite.domain.errors import ContractViolation


_RANKDIR = {
    "radial": "LR",
    "hierarchy": "TB",
    "tree": "TB",
    "flow": "LR",
}
_SHAPES = {
    "environment": "ellipse",
    "stakeholder": "box",
    "requirement": "note",
    "technical_requirement": "note",
    "function": "box",
    "logical_component": "component",
    "physical_block": "box3d",
    "operational_scenario": "oval",
    "lifecycle_phase": "hexagon",
    "interface": "parallelogram",
}
_EDGE_COLORS = {
    "satisfiedBy": "#2563eb",
    "allocatedTo": "#7c3aed",
    "realizedBy": "#0f766e",
    "refines": "#b45309",
    "interfacesWith": "#0891b2",
    "transitionsTo": "#475569",
}


def _quote(value: object) -> str:
    text = str(value or "")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def _node_label(item: dict[str, object]) -> str:
    name = str(item.get("name", item.get("id", "")))
    kind = str(item.get("kind", ""))
    needs = "\n[待补充分析]" if item.get("needs_analysis") else ""
    return f"{name}\n<{kind}>{needs}"


def _cluster_for(item: dict[str, object]) -> str:
    kind = str(item.get("kind", ""))
    if kind in {"requirement", "technical_requirement"}:
        return "requirements"
    if kind in {"function"}:
        return "functional"
    if kind in {"logical_component", "interface"}:
        return "logical"
    if kind in {"physical_block"}:
        return "physical"
    return "operational"


def compile_graphviz_view(model: object, view_id: str, options: dict[str, object] | None = None) -> str:
    del options
    definition = view_definition(view_id)
    semantic = semantic_model_for_view(model)
    entities = view_entities(semantic, definition.id)
    relations = view_relations(semantic, definition.id)
    ids = {str(item.get("id")) for item in entities}
    rankdir = _RANKDIR.get(definition.layout, "LR")
    lines = [
        "digraph MBSE {",
        f"  graph [rankdir={rankdir}, bgcolor=\"transparent\", pad=0.25, nodesep=0.42, ranksep=0.65, splines=ortho];",
        "  node [fontname=\"Arial\", fontsize=10, style=\"rounded,filled\", color=\"#64748b\", fillcolor=\"#f8fafc\", fontcolor=\"#0f172a\", margin=0.16];",
        "  edge [fontname=\"Arial\", fontsize=9, color=\"#64748b\", arrowsize=0.7];",
    ]
    clusters: dict[str, list[dict[str, object]]] = {}
    for item in entities:
        clusters.setdefault(_cluster_for(item), []).append(item)
    for cluster, cluster_items in sorted(clusters.items()):
        if definition.id not in {"rflp", "environment", "function_interaction", "logical_interaction", "physical_interaction"}:
            lines.extend([
                f"  subgraph cluster_{cluster} {{",
                f"    label={_quote(cluster.title())};",
                "    color=\"#cbd5e1\";",
                "    style=\"rounded,dashed\";",
            ])
        for item in cluster_items:
            item_id = str(item.get("id", ""))
            shape = _SHAPES.get(str(item.get("kind", "")), "box")
            lines.append(
                f"    {_quote(item_id)} [label={_quote(_node_label(item))}, shape={shape}];"
            )
        if definition.id not in {"rflp", "environment", "function_interaction", "logical_interaction", "physical_interaction"}:
            lines.append("  }")
    for relation in relations:
        source_id = str(relation.get("source_id", ""))
        target_id = str(relation.get("target_id", ""))
        if source_id not in ids or target_id not in ids:
            continue
        kind = str(relation.get("kind", "relatedTo"))
        color = _EDGE_COLORS.get(kind, "#64748b")
        label = _quote(kind)
        lines.append(
            f"  {_quote(source_id)} -> {_quote(target_id)} [label={label}, color={_quote(color)}, fontcolor={_quote(color)}];"
        )
    if not entities:
        lines.append('  empty [label="暂无可用语义", shape=note, fillcolor="#fff7ed"];')
    lines.append("}")
    return "\n".join(lines) + "\n"


def graphviz_view_metadata(model: object, view_id: str) -> dict[str, object]:
    definition = view_definition(view_id)
    semantic = semantic_model_for_view(model)
    entities = view_entities(semantic, definition.id)
    return {
        "view_id": definition.id,
        "layout": definition.layout,
        "rankdir": _RANKDIR.get(definition.layout, "LR"),
        "nodes": tuple(entities),
        "edges": tuple(view_relations(semantic, definition.id)),
    }
