"""Allowlisted, bounded ModelGraph context selection."""

from __future__ import annotations

from typing import Any

from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.context_planner import ContextPlanner
from rflp_lite.methodology.contracts import ContextBundle, TaskSpec
from rflp_lite.retrieval.planner import KnowledgeGap, build_gap_query


class ContextBuilder:
    def __init__(self, retrieval_engine: Any | None = None, *, retrieval: Any | None = None, planner: ContextPlanner | None = None):
        self.retrieval_engine = retrieval_engine or retrieval
        self.planner = planner or ContextPlanner()

    def build(
        self,
        graph: ModelGraph,
        task: TaskSpec,
        *,
        knowledge_gap: KnowledgeGap | None = None,
        root_entity_ids: tuple[str, ...] = (),
        token_budget: int = 2000,
    ) -> ContextBundle:
        planned = self.planner.plan(graph, task, root_entity_ids=root_entity_ids, token_budget=token_budget)
        context = ContextBundle(graph.project_id, task.id, graph.revision, planned.entities, planned.relations, (), planned.token_estimate)
        if self.retrieval_engine is None or not task.context_query.include_evidence:
            return context
        gap = knowledge_gap or KnowledgeGap(
            code=f"task.{task.id}",
            query=build_gap_query(task, planned.entities, None, context),
            required_kinds=tuple(kind.value for kind in task.input_kinds),
        )
        if knowledge_gap is not None:
            gap = KnowledgeGap(gap.code, build_gap_query(task, planned.entities, knowledge_gap, context), gap.description, gap.required_kinds)
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
            context.relations, evidence, context.token_estimate + sum(self.planner.estimator.estimate(item) for item in evidence),
        )
