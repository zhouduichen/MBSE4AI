"""Allowlisted, bounded ModelGraph context selection."""

from __future__ import annotations

from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.contracts import ContextBundle, TaskSpec


class ContextBuilder:
    def build(self, graph: ModelGraph, task: TaskSpec) -> ContextBundle:
        allowed = task.context_query.entity_kinds
        entities = tuple(item for item in graph.entities if item.kind in allowed)
        selected_ids = {item.id for item in entities}
        relations = tuple(
            relation for relation in graph.relations
            if relation.source_id in selected_ids or relation.target_id in selected_ids
        )
        token_estimate = sum(len(item.meta.name) + len(str(item.payload)) for item in entities)
        return ContextBundle(graph.project_id, task.id, graph.revision, entities, relations, (), token_estimate)
