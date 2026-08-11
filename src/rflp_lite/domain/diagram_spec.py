"""Renderer-independent, deterministic diagram value objects."""

from __future__ import annotations

from dataclasses import dataclass

from rflp_lite.domain.canonical import canonical_hash, to_primitive


@dataclass(frozen=True, slots=True)
class DiagramGroup:
    id: str
    label: str
    order: int


@dataclass(frozen=True, slots=True)
class DiagramNode:
    source_id: str
    label: str
    kind: str
    status: str
    group_id: str = ""
    parent_id: str = ""
    detail: str = ""
    order: int = 0


@dataclass(frozen=True, slots=True)
class DiagramEdge:
    id: str
    source_id: str
    target_id: str
    predicate: str
    label: str = ""
    order: int = 0


@dataclass(frozen=True, slots=True)
class DiagramSpec:
    id: str
    format: str
    version: int
    diagram_type: str
    title: str
    source_graph_hash: str
    groups: tuple[DiagramGroup, ...]
    nodes: tuple[DiagramNode, ...]
    edges: tuple[DiagramEdge, ...]
    warnings: tuple[str, ...] = ()
    theme: str = "cesam-light-v1"

    @classmethod
    def create(cls, *, diagram_type: str, title: str, source_graph_hash: str, groups: tuple[DiagramGroup, ...], nodes: tuple[DiagramNode, ...], edges: tuple[DiagramEdge, ...], warnings: tuple[str, ...] = (), theme: str = "cesam-light-v1") -> "DiagramSpec":
        node_ids = [item.source_id for item in nodes]
        group_ids = [item.id for item in groups]
        edge_ids = [item.id for item in edges]
        if len(node_ids) != len(set(node_ids)) or len(group_ids) != len(set(group_ids)) or len(edge_ids) != len(set(edge_ids)):
            raise ValueError("diagram IDs must be unique")
        known = set(node_ids)
        if any(item.source_id not in known or item.target_id not in known for item in edges):
            raise ValueError("diagram edge reference is invalid")
        if any(item.group_id and item.group_id not in set(group_ids) for item in nodes):
            raise ValueError("diagram group reference is invalid")
        if any(item.parent_id and item.parent_id not in known for item in nodes):
            raise ValueError("diagram parent reference is invalid")
        payload = {"diagram_type": diagram_type, "title": title, "source_graph_hash": source_graph_hash, "groups": groups, "nodes": nodes, "edges": edges, "theme": theme}
        return cls(f"diagram-{canonical_hash(payload)[:16]}", "ai4mbse/diagram-spec", 1, diagram_type, title, source_graph_hash, groups, nodes, edges, warnings, theme)

    def as_dict(self) -> dict[str, object]:
        return to_primitive(self)
