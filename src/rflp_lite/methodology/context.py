"""Allowlisted, bounded ModelGraph context selection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from rflp_lite.domain.entities import Entity, EntityKind, EntityStatus
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.context_planner import ContextPlanner, PlannedContext
from rflp_lite.methodology.contracts import ContextBundle, TaskSpec
from rflp_lite.methodology.engine import MethodologyEngine
from rflp_lite.methodology.trace_rules import requirement_trace_scope
from rflp_lite.retrieval.planner import KnowledgeGap, build_gap_query


_ASSURANCE_TRACE_KINDS = frozenset({
    # V&V payloads must be grounded in the same downstream scope that the
    # completion and methodology engines derive from the graph.
    EntityKind.REQUIREMENT,
    EntityKind.FUNCTION,
    EntityKind.LOGICAL_COMPONENT,
    EntityKind.PHYSICAL_BLOCK,
    EntityKind.OPERATIONAL_SCENARIO,
    EntityKind.FUNCTIONAL_SCENARIO,
    EntityKind.ACTIVITY,
    EntityKind.VERIFICATION_CASE,
    EntityKind.VALIDATION_CASE,
    EntityKind.HAZARD,
    EntityKind.FAILURE_MODE,
})
_ASSURANCE_SUPPORT_KINDS = frozenset({
    EntityKind.OPERATIONAL_SCENARIO,
    EntityKind.FUNCTIONAL_SCENARIO,
    EntityKind.ACTIVITY,
    EntityKind.HAZARD,
    EntityKind.FAILURE_MODE,
})
_ASSURANCE_TASK_IDS = frozenset({
    "verification_validation",
    "global_cross_analysis",
    "vertical.verification_validation",
    "vertical.global_cross_analysis",
})
_INACTIVE_STATUSES = frozenset({
    EntityStatus.REJECTED,
    EntityStatus.DEPRECATED,
})
_READY_STATUSES = frozenset({
    EntityStatus.VALIDATED,
    EntityStatus.ACCEPTED,
    EntityStatus.LOCKED,
})


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
        evidence_bundle: Sequence[Mapping[str, object]] = (),
    ) -> ContextBundle:
        total_budget = max(0, int(token_budget))
        if output_reserve is None:
            output_reserve = max(128, min(1024, total_budget // 4))
        available_context = max(
            0,
            total_budget - max(0, int(output_reserve)) - max(0, int(prompt_reserve)),
        )
        effective_root_entity_ids = root_entity_ids
        if not effective_root_entity_ids:
            effective_root_entity_ids = {
                "functional_requirement": _functional_requirement_context_roots(graph),
                "physical_candidates": _physical_candidate_context_roots(graph),
                "allocation_tradeoff": _allocation_tradeoff_context_roots(graph),
                "technical_requirement": _technical_context_roots(graph),
            }.get(task.id, ())
        planned = self.planner.plan(
            graph,
            task,
            root_entity_ids=effective_root_entity_ids,
            token_budget=available_context,
        )
        assurance_guidance: Mapping[str, object] = {}
        if task.id in _ASSURANCE_TASK_IDS:
            planned, assurance_guidance = _assurance_trace_context(
                graph, self.planner, available_context, task.id
            )
        methodology_guidance = dict(
            self.methodology_engine.context_guidance(graph, task.id)
        )
        if assurance_guidance:
            methodology_guidance["context_selection"] = assurance_guidance
        context = ContextBundle(
            graph.project_id,
            task.id,
            graph.revision,
            planned.entities,
            planned.relations,
            (),
            planned.token_estimate,
            methodology_guidance=methodology_guidance,
        )
        baseline_evidence = _unique_evidence(evidence_bundle)
        if self.retrieval_engine is None or not task.context_query.include_evidence:
            return _with_bounded_evidence(
                context, baseline_evidence, available_context, self.planner
            )
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
        return _with_bounded_evidence(
            context,
            _unique_evidence((*baseline_evidence, *evidence)),
            available_context,
            self.planner,
        )


def _unique_evidence(
    values: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    unique: list[Mapping[str, object]] = []
    seen: set[tuple[str, ...]] = set()
    for value in values:
        if not isinstance(value, Mapping):
            continue
        item = dict(value)
        key = (
            str(item.get("id", "")),
            str(item.get("source_id", "")),
            str(item.get("locator", "")),
            str(item.get("excerpt", item.get("text", ""))),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return tuple(unique)


def _with_bounded_evidence(
    context: ContextBundle,
    evidence: Sequence[Mapping[str, object]],
    available_context: int,
    planner: ContextPlanner,
) -> ContextBundle:
    remaining = max(0, available_context - context.token_estimate)
    bounded: list[Mapping[str, object]] = []
    for value in evidence:
        item = dict(value)
        estimate = planner.estimator.estimate(item)
        if estimate > remaining:
            continue
        bounded.append(item)
        remaining -= estimate
    return ContextBundle(
        context.project_id,
        context.task_id,
        context.revision,
        context.entities,
        context.relations,
        tuple(bounded),
        context.token_estimate + sum(
            planner.estimator.estimate(item) for item in bounded
        ),
        context.controller_decisions,
        context.methodology_guidance,
    )


def _assurance_trace_context(
    graph: ModelGraph,
    planner: ContextPlanner,
    token_budget: int,
    task_id: str,
) -> tuple[PlannedContext, Mapping[str, object]]:
    """Select a bounded, deterministic trace slice for assurance tasks."""

    active = {
        item.id: item
        for item in graph.entities
        if item.kind in _ASSURANCE_TRACE_KINDS
        and item.meta.status not in _INACTIVE_STATUSES
    }
    requirements = tuple(sorted(
        (
            item for item in active.values()
            if item.kind is EntityKind.REQUIREMENT
        ),
        key=lambda item: item.id,
    ))
    scopes = {
        item.id: requirement_trace_scope(graph, item.id)
        for item in requirements
    }

    # Reserve the first pass for every Requirement so a large project does not
    # spend its entire budget on the first requirement's downstream path.
    priority_ids: list[str] = [item.id for item in requirements]
    if task_id not in {"global_cross_analysis", "vertical.global_cross_analysis"}:
        for field in (
            "function_ids",
            "logical_component_ids",
            "physical_ids",
        ):
            priority_ids.extend(
                target_id
                for requirement in requirements
                for target_id in sorted(
                    (
                        item_id for item_id in getattr(scopes[requirement.id], field)
                        if item_id in active
                    ),
                    key=lambda item_id: (
                        active[item_id].meta.status not in _READY_STATUSES,
                        item_id,
                    ),
                )
            )
    requirement_ids = {item.id for item in requirements}
    priority_ids.extend(
        _matching_vv_ids(graph, requirement_ids, active)
    )
    primary_ids = set(priority_ids)
    support_entities = sorted(
        (
            item for item in active.values()
            if item.kind in _ASSURANCE_SUPPORT_KINDS
        ),
        key=lambda item: (
            not (
                _references_any(item.payload, primary_ids)
                or _has_selected_endpoint(graph, item.id, primary_ids)
            ),
            item.id,
        ),
    )
    priority_ids.extend(item.id for item in support_entities)
    priority_ids = list(dict.fromkeys(
        item_id for item_id in priority_ids if item_id in active
    ))

    selected: set[str] = set()
    available_budget = max(0, int(token_budget))
    for item_id in priority_ids:
        candidate = selected | {item_id}
        relations = _selected_relations(graph, candidate)
        if planner._estimate(graph, candidate, relations) <= available_budget:
            selected.add(item_id)

    entities = tuple(sorted(
        (active[item_id] for item_id in selected),
        key=lambda item: item.id,
    ))
    relations = _selected_relations(graph, selected)
    planned = PlannedContext(
        entities,
        relations,
        planner._estimate(graph, selected, relations),
        (
            ("REQUIREMENTS", tuple(
                item.id for item in requirements if item.id in selected
            )),
            ("RFLP_SCOPE", tuple(sorted(
                selected & {
                    target_id
                    for scope in scopes.values()
                    for target_id in (
                        scope.function_ids
                        + scope.logical_component_ids
                        + scope.physical_ids
                    )
                }
            ))),
            ("V_AND_V", tuple(sorted(
                selected
                & {
                    item_id for item_id in priority_ids
                    if active[item_id].kind in {
                        EntityKind.VERIFICATION_CASE,
                        EntityKind.VALIDATION_CASE,
                    }
                }
            ))),
            ("SUPPORT", tuple(sorted(
                selected
                & {
                    item_id for item_id in priority_ids
                    if active[item_id].kind in _ASSURANCE_SUPPORT_KINDS
                }
            ))),
        ),
    )
    active_ids = set(active)
    selected_requirement_ids = tuple(sorted(
        requirement_ids & selected
    ))
    guidance = {
        "policy": "requirement-first-rflp-vv-support",
        "available_budget": available_budget,
        "token_estimate": planned.token_estimate,
        "selected_entity_ids": list(sorted(selected)),
        "omitted_entity_ids": list(sorted(active_ids - selected)),
        "selected_requirement_ids": list(selected_requirement_ids),
        "omitted_requirement_ids": list(sorted(
            requirement_ids - selected
        )),
        "requirement_scopes": {
            requirement_id: scopes[requirement_id].as_dict()
            for requirement_id in sorted(scopes)
        },
    }
    return planned, guidance


def _matching_vv_ids(
    graph: ModelGraph,
    requirement_ids: set[str],
    active: Mapping[str, Entity],
) -> tuple[str, ...]:
    matching: set[str] = set()
    vv_kinds = {
        EntityKind.VERIFICATION_CASE,
        EntityKind.VALIDATION_CASE,
    }
    vv_predicates = {
        RelationPredicate.VERIFIED_BY,
        RelationPredicate.VALIDATED_BY,
    }
    for relation in graph.relations:
        target = active.get(relation.target_id)
        if (
            relation.source_id in requirement_ids
            and relation.predicate in vv_predicates
            and target is not None
            and target.kind in vv_kinds
        ):
            matching.add(target.id)
    return tuple(sorted(matching))


def _selected_relations(
    graph: ModelGraph,
    selected: set[str],
) -> tuple[Relation, ...]:
    return tuple(sorted(
        (
            relation for relation in graph.relations
            if relation.source_id in selected and relation.target_id in selected
        ),
        key=lambda item: item.id,
    ))


def _references_any(value: object, candidate_ids: set[str]) -> bool:
    if isinstance(value, str):
        return value in candidate_ids
    if isinstance(value, Mapping):
        return any(_references_any(item, candidate_ids) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_references_any(item, candidate_ids) for item in value)
    return False


def _has_selected_endpoint(
    graph: ModelGraph,
    entity_id: str,
    candidate_ids: set[str],
) -> bool:
    return any(
        (
            relation.source_id == entity_id
            and relation.target_id in candidate_ids
        )
        or (
            relation.target_id == entity_id
            and relation.source_id in candidate_ids
        )
        for relation in graph.relations
    )


def _technical_context_roots(graph: ModelGraph) -> tuple[str, ...]:
    """Keep every explicit constraint and its physical candidate in scope."""

    requirements = tuple(
        item
        for item in graph.entities
        if item.kind is EntityKind.REQUIREMENT
        and str(item.payload.get("level", "")).strip().lower() != "technical"
        and (
            bool(item.payload.get("constraints"))
            or any(str(key).startswith(("max_", "min_")) for key in item.payload)
        )
    )
    requirement_ids = {item.id for item in requirements}
    physical_ids = {
        item.id
        for item in graph.entities
        if item.kind is EntityKind.PHYSICAL_BLOCK
        and requirement_ids.intersection(
            str(source_id)
            for source_id in item.payload.get("source_requirement_ids", ())
        )
    }
    return tuple(sorted((*requirement_ids, *physical_ids)))


def _functional_requirement_context_roots(graph: ModelGraph) -> tuple[str, ...]:
    """Keep every Requirement and its directly allocated Function in scope."""

    requirement_ids = {
        item.id
        for item in graph.entities
        if item.kind is EntityKind.REQUIREMENT
        and str(item.payload.get("level", "")).strip().lower() != "technical"
    }
    function_ids = {
        item.id
        for item in graph.entities
        if item.kind is EntityKind.FUNCTION
        and (
            str(item.payload.get("requirement_id", "")).strip() in requirement_ids
            or any(
                relation.source_id in requirement_ids
                and relation.target_id == item.id
                and relation.predicate.value == "satisfiedBy"
                for relation in graph.relations
            )
        )
    }
    return tuple(sorted((*requirement_ids, *function_ids)))


def _physical_candidate_context_roots(graph: ModelGraph) -> tuple[str, ...]:
    """Keep every Function→Logical allocation available for physical mapping."""

    requirement_ids = {
        item.id
        for item in graph.entities
        if item.kind is EntityKind.REQUIREMENT
        and str(item.payload.get("level", "")).strip().lower() != "technical"
    }
    logical_ids = {
        item.id for item in graph.entities if item.kind is EntityKind.LOGICAL_COMPONENT
    }
    function_ids = {
        relation.source_id
        for relation in graph.relations
        if relation.predicate.value == "allocatedTo"
        and relation.target_id in logical_ids
        and graph.entity_index.get(relation.source_id) is not None
        and graph.entity_index[relation.source_id].kind is EntityKind.FUNCTION
    }
    return tuple(sorted((*requirement_ids, *logical_ids, *function_ids)))


def _allocation_tradeoff_context_roots(graph: ModelGraph) -> tuple[str, ...]:
    """Keep every logical/physical pair available for trade-study updates."""

    return tuple(sorted(
        item.id
        for item in graph.entities
        if item.kind in {EntityKind.LOGICAL_COMPONENT, EntityKind.PHYSICAL_BLOCK}
    ))
