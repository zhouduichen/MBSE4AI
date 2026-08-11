"""Build deterministic diagram specifications from accepted semantic graphs."""

from __future__ import annotations

from rflp_lite.domain.diagram_spec import DiagramEdge, DiagramGroup, DiagramNode, DiagramSpec
from rflp_lite.domain.errors import ContractViolation


DIAGRAM_TYPES = (
    "stakeholder_hierarchy", "environment", "requirements", "lifecycle", "operational_decomposition", "operational_sequence", "functional_decomposition", "functional_interaction", "functional_sequence", "logical_decomposition", "logical_interaction", "physical_allocation", "physical_interaction", "technical_requirements", "traceability",
)

TYPE_FILTERS = {
    "stakeholder_hierarchy": {"stakeholder"}, "environment": {"system_boundary", "stakeholder", "exchange_flow"}, "requirements": {"concern", "need", "requirement"}, "lifecycle": {"lifecycle_phase", "transition"}, "operational_decomposition": {"use_case", "operational_scenario"}, "operational_sequence": {"stakeholder", "operational_scenario", "exchange_flow"}, "functional_decomposition": {"capability", "function"}, "functional_interaction": {"function", "functional_flow"}, "functional_sequence": {"function", "functional_scenario", "functional_flow"}, "logical_decomposition": {"logical_component"}, "logical_interaction": {"logical_component", "interface"}, "physical_allocation": {"logical_component", "physical_block"}, "physical_interaction": {"physical_block", "interface"}, "technical_requirements": {"physical_block", "requirement"}, "traceability": set(),
}


def _group_for(kind: str, pack: dict[str, object]) -> str:
    mapping = {"stakeholder": "stakeholder_context", "system_boundary": "stakeholder_context", "exchange_flow": "stakeholder_context", "operational_scenario": "scenario_flow", "use_case": "scenario_flow", "function": "functional_decomposition", "capability": "functional_decomposition", "logical_component": "logical_architecture", "physical_block": "physical_architecture", "requirement": "traceability"}
    candidate = mapping.get(kind, "")
    groups = pack.get("diagram_groups", {})
    return candidate if isinstance(groups, dict) and candidate in groups else ""


def build_diagram_spec(graph: dict[str, object], diagram_type: str, pack: dict[str, object]) -> DiagramSpec:
    if diagram_type not in DIAGRAM_TYPES:
        raise ContractViolation(f"unsupported diagram type: {diagram_type}")
    elements = [item for item in graph.get("elements", []) if isinstance(item, dict) and item.get("status") == "accepted"]
    allowed = TYPE_FILTERS[diagram_type]
    selected = elements if diagram_type == "traceability" else [item for item in elements if item.get("kind") in allowed]
    selected_ids = {str(item.get("id", "")) for item in selected}
    group_data = pack.get("diagram_groups", {})
    groups = tuple(DiagramGroup(str(key), str(value.get("label", key)), int(value.get("order", 0))) for key, value in sorted(group_data.items(), key=lambda pair: (int(pair[1].get("order", 0)), str(pair[0]))) if isinstance(group_data, dict) and isinstance(value, dict))
    nodes = []
    for item in sorted(selected, key=lambda value: (str(value.get("kind", "")), str(value.get("name", "")), str(value.get("id", "")))):
        attributes = item.get("attributes", {}) if isinstance(item.get("attributes"), dict) else {}
        detail = next((str(attributes.get(key)) for key in ("statement", "description", "scenario_type", "requirement_type") if attributes.get(key)), "")
        nodes.append(DiagramNode(str(item.get("id", "")), str(item.get("name", "")), str(item.get("kind", "")), "accepted", _group_for(str(item.get("kind", "")), pack), str(attributes.get("parent_id", "")), detail, int(attributes.get("order", 0))))
    edges = []
    for index, relation in enumerate(graph.get("relations", []) if isinstance(graph.get("relations"), list) else []):
        if not isinstance(relation, dict) or str(relation.get("source_id")) not in selected_ids or str(relation.get("target_id")) not in selected_ids:
            continue
        edges.append(DiagramEdge(str(relation.get("id", f"edge-{index}")), str(relation["source_id"]), str(relation["target_id"]), str(relation.get("predicate", "relatedTo")), str(relation.get("label", "")), index))
    title = str((group_data.get(diagram_type, {}) if isinstance(group_data, dict) else {}).get("label", diagram_type))
    return DiagramSpec.create(diagram_type=diagram_type, title=title, source_graph_hash=str(graph.get("graph_hash", "")), groups=groups, nodes=tuple(nodes), edges=tuple(edges))


def split_diagram_spec(spec: DiagramSpec, max_nodes: int = 40) -> tuple[DiagramSpec, ...]:
    if max_nodes < 1:
        raise ValueError("max_nodes must be positive")
    nodes = sorted(spec.nodes, key=lambda node: (node.group_id, node.kind, node.label, node.source_id))
    if len(nodes) <= max_nodes:
        return (spec,)
    pages = [nodes[index:index + max_nodes] for index in range(0, len(nodes), max_nodes)]
    result = []
    for index, page_nodes in enumerate(pages, start=1):
        ids = {node.source_id for node in page_nodes}
        page_edges = tuple(edge for edge in spec.edges if edge.source_id in ids and edge.target_id in ids)
        result.append(DiagramSpec.create(diagram_type=spec.diagram_type, title=f"{spec.title}（{index}/{len(pages)}）", source_graph_hash=spec.source_graph_hash, groups=spec.groups, nodes=tuple(page_nodes), edges=page_edges, warnings=spec.warnings + (f"图形已按 {max_nodes} 个节点拆分",), theme=spec.theme))
    return tuple(result)
