"""Deterministic TaskSpec completion-condition evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from rflp_lite.domain.entities import Entity, EntityKind, EntityStatus
from rflp_lite.domain.model import ModelGraph
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.contracts import TaskExecutionResponse, TaskSpec
from rflp_lite.methodology.coverage_matrix import build_requirement_coverage
from rflp_lite.methodology.trace_rules import vv_scope_matches
from rflp_lite.methodology.vertical_generation import VerticalStageSpec, stage_spec
from rflp_lite.methodology.vertical_coverage import resolve_vertical_coverage


@dataclass(frozen=True, slots=True)
class CompletionResult:
    passed: bool
    checks: tuple[Mapping[str, object], ...] = ()
    issue_codes: tuple[str, ...] = ()


def evaluate_vertical_stage(
    stage: VerticalStageSpec | str,
    graph: ModelGraph,
) -> CompletionResult:
    """Evaluate the fine-grained reasoning tasks behind one product stage."""

    spec = stage_spec(stage)
    checks: list[Mapping[str, object]] = []
    issues: list[str] = []
    for task_id in spec.reasoning_tasks:
        passed = _lifecycle_semantics_passed(task_id, graph)
        checks.append({"id": task_id, "passed": passed})
        if not passed:
            issues.append(f"completion_semantic:{task_id}")
    coverage_stage = {
        "functional": "functional",
        "logical": "logical",
        "physical": "physical",
        "verification_validation": "verification_validation",
    }.get(spec.stage.value)
    if coverage_stage is not None:
        coverage = resolve_vertical_coverage(graph, coverage_stage)
        checks.append(dict(coverage.as_check()))
        if not coverage.passed:
            issues.append(f"completion_requirement_coverage:{coverage_stage}")
    return CompletionResult(not issues, tuple(checks), tuple(issues))


def evaluate_completion(task: TaskSpec, graph: ModelGraph, response: TaskExecutionResponse | None = None) -> CompletionResult:
    condition = task.completion_condition
    active = tuple(entity for entity in graph.entities if entity.meta.status is not EntityStatus.DEPRECATED)
    output_entities = tuple(entity for entity in active if entity.kind in condition.required_output_kinds)
    checks: list[Mapping[str, object]] = []
    issues: list[str] = []
    if condition.minimum_entities:
        count_ok = len(output_entities) >= condition.minimum_entities
        checks.append({"id": "minimum_entities", "passed": count_ok, "actual": len(output_entities), "expected": condition.minimum_entities})
        if not count_ok:
            issues.append("completion_minimum_entities")
    elif response is not None and response.patch is not None and condition.required_output_kinds:
        produced_kinds = {operation.entity.kind for operation in response.patch.operations if hasattr(operation, "entity")}
        kinds_ok = condition.required_output_kinds <= produced_kinds or bool(output_entities)
        checks.append({"id": "required_output_kinds", "passed": kinds_ok, "actual": sorted(kind.value for kind in produced_kinds), "expected": sorted(kind.value for kind in condition.required_output_kinds)})
        if not kinds_ok:
            issues.append("completion_output_kinds")
    if condition.require_accepted:
        accepted_ok = bool(output_entities) and all(entity.meta.status is EntityStatus.ACCEPTED for entity in output_entities)
        checks.append({"id": "require_accepted", "passed": accepted_ok})
        if not accepted_ok:
            issues.append("completion_requires_accepted")
    matrix = build_requirement_coverage(graph)
    for rule in condition.required_trace_rules:
        passed = _trace_rule_passed(rule, matrix.metrics)
        checks.append({"id": rule, "passed": passed})
        if not passed:
            issues.append(f"completion_trace:{rule}")
    if response is not None and _is_lifecycle_response(response):
        passed = _lifecycle_semantics_passed(task.id, graph)
        checks.append({"id": f"semantic:{task.id}", "passed": passed})
        if not passed:
            issues.append(f"completion_semantic:{task.id}")
    return CompletionResult(not issues, tuple(checks), tuple(issues))


def _is_lifecycle_response(response: TaskExecutionResponse) -> bool:
    return any(
        diagnostic.startswith(("offline:lifecycle-", "lifecycle:structured"))
        for diagnostic in response.diagnostics
    )


def _lifecycle_semantics_passed(task_id: str, graph: ModelGraph) -> bool:
    active = tuple(
        entity for entity in graph.entities
        if entity.meta.status is not EntityStatus.DEPRECATED
    )
    kinds = {entity.kind for entity in active}
    index = graph.entity_index
    relation_keys = {
        (item.source_id, item.predicate, item.target_id)
        for item in graph.relations
    }

    requirements = tuple(item for item in active if item.kind is EntityKind.REQUIREMENT)
    functions = tuple(item for item in active if item.kind is EntityKind.FUNCTION)
    physicals = tuple(item for item in active if item.kind is EntityKind.PHYSICAL_BLOCK)
    function_ids = {item.id for item in functions}
    explicit_constraints = any(
        bool(item.payload.get("constraints"))
        or any(str(key).startswith(("max_", "min_")) for key in item.payload)
        for item in requirements
        if str(item.payload.get("level", "")).lower() != "technical"
    )
    rules = {
        "system_definition": _has_kind(kinds, EntityKind.SYSTEM),
        "stakeholder_analysis": _has_kind(kinds, EntityKind.STAKEHOLDER)
        and _has_kind(kinds, EntityKind.CONCERN)
        and _linked(graph, index, EntityKind.STAKEHOLDER, RelationPredicate.HAS_CONCERN, EntityKind.CONCERN),
        "stakeholder_requirements": bool(requirements)
        and _linked(graph, index, EntityKind.REQUIREMENT, RelationPredicate.DERIVED_FROM, EntityKind.CONCERN),
        "lifecycle_analysis": _has_kind(kinds, EntityKind.LIFECYCLE_STAGE) and _has_kind(kinds, EntityKind.LIFECYCLE_TRANSITION),
        "scenario_exploration": _has_kind(kinds, EntityKind.SCENARIO_HYPOTHESIS),
        "use_case_analysis": _has_kind(kinds, EntityKind.USE_CASE),
        "operational_scenario": _has_kind(kinds, EntityKind.OPERATIONAL_SCENARIO)
        and _linked(graph, index, EntityKind.STAKEHOLDER, RelationPredicate.PARTICIPATES_IN, EntityKind.OPERATIONAL_SCENARIO),
        "activity_analysis": _has_kind(kinds, EntityKind.ACTIVITY),
        "system_requirement_derivation": any(
            item.payload.get("derived_by") == "system_requirement_derivation"
            for item in requirements
        ) or any(
            relation.source_id == requirement.id
            and relation.predicate is RelationPredicate.DERIVED_FROM
            and index.get(relation.target_id) is not None
            and index[relation.target_id].kind is EntityKind.ACTIVITY
            for requirement in requirements
            for relation in graph.relations
        ),
        "function_identification": bool(functions)
        and _linked(graph, index, EntityKind.REQUIREMENT, RelationPredicate.SATISFIED_BY, EntityKind.FUNCTION),
        "functional_decomposition": bool(functions)
        and all(bool(str(item.payload.get("decomposition", "")).strip()) for item in functions),
        "functional_interaction": _has_kind(kinds, EntityKind.FUNCTIONAL_FLOW)
        and _linked(graph, index, EntityKind.FUNCTION, RelationPredicate.EXCHANGES_WITH, EntityKind.FUNCTIONAL_FLOW)
        and all(
            _flow_endpoints_are_grounded(item, function_ids)
            for item in active
            if item.kind is EntityKind.FUNCTIONAL_FLOW
        ),
        "functional_scenario": _has_kind(kinds, EntityKind.FUNCTIONAL_SCENARIO)
        and all(
            _scenario_functions_are_grounded(item, function_ids)
            for item in active
            if item.kind is EntityKind.FUNCTIONAL_SCENARIO
        ),
        "functional_requirement": bool(requirements)
        and all(bool(item.payload.get("functional_behavior_ids")) for item in requirements),
        "logical_analysis": _has_kind(kinds, EntityKind.LOGICAL_COMPONENT)
        and _linked(graph, index, EntityKind.FUNCTION, RelationPredicate.ALLOCATED_TO, EntityKind.LOGICAL_COMPONENT),
        "dependency_clustering": bool(functions)
        and _has_kind(kinds, EntityKind.LOGICAL_COMPONENT)
        and all(
            any(
                source_id == function.id
                and predicate is RelationPredicate.ALLOCATED_TO
                and index.get(target_id) is not None
                and index[target_id].kind is EntityKind.LOGICAL_COMPONENT
                for source_id, predicate, target_id in relation_keys
            )
            for function in functions
        ),
        "architecture_evaluation": _has_kind(kinds, EntityKind.LOGICAL_COMPONENT)
        and all(
            str(item.payload.get("cohesion", "")).strip()
            and str(item.payload.get("coupling", "")).strip()
            and str(item.payload.get("architecture_rationale", "")).strip()
            and _has_logical_reasoning(item)
            for item in active
            if item.kind is EntityKind.LOGICAL_COMPONENT
        ),
        "physical_candidates": _has_kind(kinds, EntityKind.PHYSICAL_BLOCK)
        and _linked(graph, index, EntityKind.LOGICAL_COMPONENT, RelationPredicate.ALLOCATED_TO, EntityKind.PHYSICAL_BLOCK),
        "allocation_tradeoff": bool(physicals)
        and all(bool(item.payload.get("trade_study")) for item in physicals),
        "technical_requirement": (
            _linked(graph, index, EntityKind.REQUIREMENT, RelationPredicate.SATISFIED_BY, EntityKind.PHYSICAL_BLOCK)
            if explicit_constraints
            else any(item.payload.get("technical_requirement_status") == "no_explicit_constraints" for item in physicals)
        ),
        "constraint_propagation": bool(physicals)
        and all(
            "propagated_constraints" in item.payload
            and "source_requirement_ids" in item.payload
            for item in physicals
        ),
        "feasibility_selection": bool(physicals)
        and all(
            isinstance(item.payload.get("feasibility"), Mapping)
            and isinstance(item.payload.get("trade_study"), Mapping)
            and _has_physical_reasoning(item)
            for item in physicals
        ),
        "interface_sequence_state": _has_kind(kinds, EntityKind.INTERFACE)
        and _has_kind(kinds, EntityKind.STATE)
        and _linked(graph, index, EntityKind.LOGICAL_COMPONENT, RelationPredicate.CONNECTED_TO, EntityKind.INTERFACE)
        and _linked(graph, index, EntityKind.LOGICAL_COMPONENT, RelationPredicate.DECOMPOSES, EntityKind.STATE),
        "fmea_stpa_hazard": _has_kind(kinds, EntityKind.HAZARD)
        and _has_kind(kinds, EntityKind.FAILURE_MODE)
        and _linked(graph, index, EntityKind.HAZARD, RelationPredicate.CAUSES, EntityKind.FAILURE_MODE),
        "verification_validation": bool(requirements)
        and all(
            _linked_vv(graph, index, requirement, RelationPredicate.VERIFIED_BY, EntityKind.VERIFICATION_CASE)
            and _linked_vv(graph, index, requirement, RelationPredicate.VALIDATED_BY, EntityKind.VALIDATION_CASE)
            for requirement in requirements
        ),
        "reverse_feasibility": bool(requirements)
        and any(bool(item.payload.get("feasibility_review")) for item in requirements),
        "global_cross_analysis": bool(requirements)
        and all(
            _linked_vv(graph, index, requirement, RelationPredicate.VERIFIED_BY, EntityKind.VERIFICATION_CASE)
            and _linked_vv(graph, index, requirement, RelationPredicate.VALIDATED_BY, EntityKind.VALIDATION_CASE)
            and any(
                relation.source_id == requirement.id
                and relation.predicate is RelationPredicate.VERIFIED_BY
                and index.get(relation.target_id) is not None
                and index[relation.target_id].kind is EntityKind.VERIFICATION_CASE
                and index[relation.target_id].payload.get("cross_analysis_status") == "checked"
                for relation in graph.relations
            )
            for requirement in requirements
        ),
    }
    return bool(rules.get(task_id, True))


def _has_kind(kinds: set[EntityKind], kind: EntityKind) -> bool:
    return kind in kinds


def _linked(
    graph: ModelGraph,
    index: Mapping[str, Entity],
    source_kind: EntityKind,
    predicate: RelationPredicate,
    target_kind: EntityKind,
) -> bool:
    return any(
        index.get(item.source_id) is not None
        and index[item.source_id].kind is source_kind
        and item.predicate is predicate
        and index.get(item.target_id) is not None
        and index[item.target_id].kind is target_kind
        for item in graph.relations
    )


def _linked_vv(
    graph: ModelGraph,
    index: Mapping[str, Entity],
    requirement: Entity,
    predicate: RelationPredicate,
    target_kind: EntityKind,
) -> bool:
    return any(
        relation.source_id == requirement.id
        and relation.predicate is predicate
        and index.get(relation.target_id) is not None
        and index[relation.target_id].kind is target_kind
        and vv_scope_matches(graph, requirement.id, index[relation.target_id])
        for relation in graph.relations
    )


def _flow_endpoints_are_grounded(
    flow: Entity,
    function_ids: set[str],
) -> bool:
    source_ids = _string_ids(flow.payload.get("source_function_ids"))
    target_ids = _string_ids(flow.payload.get("target_function_ids"))
    return bool(source_ids or target_ids) and bool(
        set(source_ids + target_ids) <= function_ids
    )


def _scenario_functions_are_grounded(
    scenario: Entity,
    function_ids: set[str],
) -> bool:
    scenario_ids = _string_ids(scenario.payload.get("function_ids"))
    return bool(scenario_ids) and set(scenario_ids) <= function_ids


def _has_logical_reasoning(component: Entity) -> bool:
    reasoning = component.payload.get("architecture_reasoning")
    if not isinstance(reasoning, Mapping):
        return False
    basis = reasoning.get("basis")
    return (
        isinstance(basis, Mapping)
        and isinstance(reasoning.get("alternatives"), (list, tuple))
        and bool(str(reasoning.get("recommended_alternative", "")).strip())
        and bool(str(reasoning.get("selection_status", "")).strip())
    )


def _has_physical_reasoning(physical: Entity) -> bool:
    reasoning = physical.payload.get("feasibility_reasoning")
    if not isinstance(reasoning, Mapping):
        return False
    return all(
        key in reasoning
        for key in (
            "requirement_ids", "logical_ids", "function_ids",
            "propagated_constraints", "missing_fields", "conflicts",
            "status", "score", "resolution_options",
        )
    )


def _string_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return ()
    return tuple(
        item for item in (str(raw).strip() for raw in value) if item
    )


def _trace_rule_passed(rule: str, metrics: Mapping[str, object]) -> bool:
    aliases = {
        "requirement_to_function": "r_to_f_coverage",
        "r_to_f": "r_to_f_coverage",
        "r_to_f_to_l": "r_to_f_to_l_coverage",
        "r_to_f_to_l_to_p": "r_to_f_to_l_to_p_coverage",
        "requirement_to_verification": "r_to_v_coverage",
        "r_to_v": "r_to_v_coverage",
    }
    metric = aliases.get(rule, rule)
    value = metrics.get(metric)
    return isinstance(value, (int, float)) and float(value) >= 1.0
