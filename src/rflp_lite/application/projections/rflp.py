"""Deterministic RFLP graph and trace-focus projection."""

from __future__ import annotations

from typing import Mapping

from rflp_lite.application.projections.common import entity_card, header, issues_by_entity, requirement_trace_status
from rflp_lite.domain.entities import EntityKind, EntityStatus
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.trace_rules import rflp_paths
from rflp_lite.methodology.trace_rules import relation_is_valid_trace


_RFLP_KINDS = frozenset({EntityKind.REQUIREMENT, EntityKind.FUNCTION, EntityKind.LOGICAL_COMPONENT, EntityKind.PHYSICAL_BLOCK})


def build_rflp_view(
    graph: ModelGraph,
    issues: tuple[Mapping[str, object], ...] = (),
    *,
    selected_requirement: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    issue_only: bool = False,
    accepted_only: bool = False,
) -> Mapping[str, object]:
    issue_index = issues_by_entity(issues)
    selected_ids: set[str] = set()
    selected_trace: tuple[str, ...] = ()
    if selected_requirement and selected_requirement in graph.entity_index:
        paths = rflp_paths(graph, selected_requirement)
        selected_trace = paths[0] if paths else (selected_requirement,)
        selected_ids = {node_id for path in paths for node_id in path} | {selected_requirement}
    nodes = []
    for entity in sorted((item for item in graph.entities if item.kind in _RFLP_KINDS), key=lambda item: item.id):
        if kind and entity.kind.value != kind:
            continue
        if status and entity.meta.status.value != status:
            continue
        if accepted_only and entity.meta.status not in {EntityStatus.ACCEPTED, EntityStatus.LOCKED}:
            continue
        if issue_only and not issue_index.get(entity.id):
            continue
        card = entity_card(entity, issue_count=len(issue_index.get(entity.id, ())))
        card.update({"label": entity.meta.name, "candidate": entity.meta.status is EntityStatus.CANDIDATE, "accepted": entity.meta.status is EntityStatus.ACCEPTED, "locked": entity.meta.status is EntityStatus.LOCKED, "focused": not selected_ids or entity.id in selected_ids})
        nodes.append(card)
    node_ids = {str(node["id"]) for node in nodes}
    edges = []
    for relation in sorted(graph.relations, key=lambda item: item.id):
        if relation.source_id not in node_ids or relation.target_id not in node_ids:
            continue
        valid = relation_is_valid_trace(graph, relation.source_id, relation.target_id, relation.predicate)
        edges.append({"id": relation.id, "source": relation.source_id, "target": relation.target_id, "source_id": relation.source_id, "target_id": relation.target_id, "predicate": relation.predicate.value, "evidence_count": len(relation.evidence_ids), "valid_for_trace": valid, "focused": not selected_ids or relation.source_id in selected_ids and relation.target_id in selected_ids})
    gaps = []
    for entity in sorted((item for item in graph.entities if item.kind is EntityKind.REQUIREMENT), key=lambda item: item.id):
        trace_status, missing, trace = requirement_trace_status(graph, entity)
        if not missing:
            continue
        gaps.append({"id": f"gap-{entity.id}", "requirement_id": entity.id, "status": trace_status, "missing": list(missing), "path": list(max((path for path in rflp_paths(graph, entity.id)), default=(entity.id,), key=len)), "issue_ids": [str(issue.get("id")) for issue in issue_index.get(entity.id, ())]})
    return {**header(graph).as_dict(), "nodes": nodes, "edges": edges, "gaps": gaps, "selected_trace": list(selected_trace), "selected_requirement": selected_requirement, "filters": {"kind": kind, "status": status, "issue_only": issue_only, "accepted_only": accepted_only}, "node_count": len(nodes), "edge_count": len(edges)}
