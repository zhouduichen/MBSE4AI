"""Compile diagrams directly from the typed ModelGraph."""

from __future__ import annotations

from rflp_lite.domain.model import ModelGraph
from rflp_lite.diagrams.views import ViewSpec, kinds_for_view


def compile_model_view(graph: ModelGraph, view_id: str) -> ViewSpec:
    allowed = kinds_for_view(view_id)
    selected = tuple(
        entity for entity in graph.entities
        if entity.meta.status.value != "deprecated" and (allowed is None or entity.kind in allowed)
    )
    selected_ids = {entity.id for entity in selected}
    nodes = tuple(
        {
            "id": entity.id,
            "kind": entity.kind.value,
            "name": entity.meta.name,
            "status": entity.meta.status.value,
            "payload": dict(entity.payload),
        }
        for entity in selected
    )
    edges = tuple(
        {
            "id": relation.id,
            "source_id": relation.source_id,
            "predicate": relation.predicate.value,
            "target_id": relation.target_id,
            "evidence_ids": list(relation.evidence_ids),
        }
        for relation in graph.relations
        if relation.source_id in selected_ids and relation.target_id in selected_ids
    )
    return ViewSpec(view_id, view_id.replace("_", " ").title(), graph.snapshot_hash, nodes, edges)
