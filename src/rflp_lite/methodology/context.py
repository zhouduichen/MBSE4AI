"""Allowlisted, bounded ModelGraph context selection."""

from __future__ import annotations

from typing import Any

from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.contracts import ContextBundle, TaskSpec
from rflp_lite.retrieval.planner import KnowledgeGap


class ContextBuilder:
    def __init__(self, retrieval_engine: Any | None = None, *, retrieval: Any | None = None):
        self.retrieval_engine = retrieval_engine or retrieval

    def build(
        self,
        graph: ModelGraph,
        task: TaskSpec,
        *,
        knowledge_gap: KnowledgeGap | None = None,
    ) -> ContextBundle:
        allowed = task.context_query.entity_kinds
        entities = tuple(item for item in graph.entities if item.kind in allowed)
        selected_ids = {item.id for item in entities}
        relations = tuple(
            relation for relation in graph.relations
            if relation.source_id in selected_ids or relation.target_id in selected_ids
        )
        token_estimate = sum(len(item.meta.name) + len(str(item.payload)) for item in entities)
        context = ContextBundle(graph.project_id, task.id, graph.revision, entities, relations, (), token_estimate)
        if self.retrieval_engine is None or not task.context_query.include_evidence:
            return context
        gap = knowledge_gap or KnowledgeGap(
            code=f"task.{task.id}",
            query=task.id.replace("_", " "),
            required_kinds=tuple(kind.value for kind in task.input_kinds),
        )
        result = self.retrieval_engine.retrieve(gap, context)
        converter = getattr(self.retrieval_engine, "to_evidence", None)
        evidence = tuple(
            converter(candidate) if converter is not None else {
                "id": candidate.id, "source_type": candidate.source_type,
                "source_id": candidate.source_id, "locator": candidate.locator,
                "claim": candidate.claim, "excerpt": candidate.excerpt,
                "relevance": candidate.confidence,
            }
            for candidate in result.candidates
        )
        return ContextBundle(
            context.project_id, context.task_id, context.revision, context.entities,
            context.relations, evidence, context.token_estimate + sum(len(str(item)) for item in evidence),
        )
