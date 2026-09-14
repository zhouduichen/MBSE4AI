"""Allowlisted, bounded ModelGraph context selection."""

from __future__ import annotations

from typing import Any

from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.context_planner import ContextPlanner, PlannedContext
from rflp_lite.methodology.contracts import ContextBundle, TaskSpec
from rflp_lite.methodology.engine import MethodologyEngine
from rflp_lite.retrieval.planner import KnowledgeGap, build_gap_query


class ContextBuilder:
    def __init__(self, retrieval_engine: Any | None = None, *, retrieval: Any | None = None, planner: ContextPlanner | None = None, methodology_engine: MethodologyEngine | None = None):
        self.retrieval_engine = retrieval_engine or retrieval
        self.planner = planner or ContextPlanner()
        self.methodology_engine = methodology_engine or MethodologyEngine()

    def build(
        self,
        graph: ModelGraph,
        task: TaskSpec,
        *,
        knowledge_gap: KnowledgeGap | None = None,
        root_entity_ids: tuple[str, ...] = (),
        token_budget: int = 2000,
        output_reserve: int | None = None,
        prompt_reserve: int = 0,
    ) -> ContextBundle:
        total_budget = max(0, int(token_budget))
        if output_reserve is None:
            output_reserve = max(128, min(1024, total_budget // 4))
        available_context = max(
            0,
            total_budget - max(0, int(output_reserve)) - max(0, int(prompt_reserve)),
        )
        planned = self.planner.plan(
            graph,
            task,
            root_entity_ids=root_entity_ids,
            token_budget=available_context,
        )
        if task.id == "global_cross_analysis":
            planned = _global_analysis_context(graph, task, self.planner)
        context = ContextBundle(
            graph.project_id,
            task.id,
            graph.revision,
            planned.entities,
            planned.relations,
            (),
            planned.token_estimate,
            methodology_guidance=self.methodology_engine.context_guidance(graph, task.id),
        )
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
        remaining = max(0, available_context - planned.token_estimate)
        bounded_evidence: list[dict[str, object]] = []
        for item in evidence:
            estimate = self.planner.estimator.estimate(item)
            if estimate > remaining:
                continue
            bounded_evidence.append(item)
            remaining -= estimate
        return ContextBundle(
            context.project_id, context.task_id, context.revision, context.entities,
            context.relations, tuple(bounded_evidence),
            context.token_estimate + sum(self.planner.estimator.estimate(item) for item in bounded_evidence),
            context.controller_decisions,
            context.methodology_guidance,
        )


def _global_analysis_context(graph: ModelGraph, task: TaskSpec, planner: ContextPlanner):
    """Keep the final cross-analysis task complete over all coverage-critical nodes."""

    allowed = task.context_query.entity_kinds
    entities = tuple(
        sorted(
            (item for item in graph.entities if item.kind in allowed),
            key=lambda item: item.id,
        )
    )
    ids = {item.id for item in entities}
    relations = tuple(
        sorted(
            (item for item in graph.relations if item.source_id in ids and item.target_id in ids),
            key=lambda item: item.id,
        )
    )
    return PlannedContext(
        entities,
        relations,
        planner._estimate(graph, ids, relations),
        (("GLOBAL_COVERAGE", tuple(item.id for item in entities)),),
    )
