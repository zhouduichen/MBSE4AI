"""Deterministic TaskSpec completion-condition evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from rflp_lite.domain.entities import EntityKind, EntityStatus
from rflp_lite.domain.model import ModelGraph
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.contracts import TaskExecutionResponse, TaskSpec
from rflp_lite.methodology.coverage_matrix import build_requirement_coverage
from rflp_lite.methodology.vertical_generation import VerticalStageSpec, stage_spec


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

    def has(kind: EntityKind) -> bool:
        return kind in kinds

    def linked(source_kind: EntityKind, predicate, target_kind: EntityKind) -> bool:
        return any(
            index.get(item.source_id) is not None
            and index[item.source_id].kind is source_kind
            and item.predicate is predicate
            and index.get(item.target_id) is not None
            and index[item.target_id].kind is target_kind
            for item in graph.relations
        )

    requirements = tuple(item for item in active if item.kind is EntityKind.REQUIREMENT)
    functions = tuple(item for item in active if item.kind is EntityKind.FUNCTION)
    physicals = tuple(item for item in active if item.kind is EntityKind.PHYSICAL_BLOCK)
    explicit_constraints = any(
        bool(item.payload.get("constraints"))
        or any(str(key).startswith(("max_", "min_")) for key in item.payload)
        for item in requirements
        if str(item.payload.get("level", "")).lower() != "technical"
    )
    rules = {
        "system_definition": has(EntityKind.SYSTEM),
        "stakeholder_analysis": has(EntityKind.STAKEHOLDER)
        and has(EntityKind.CONCERN)
        and linked(EntityKind.STAKEHOLDER, RelationPredicate.HAS_CONCERN, EntityKind.CONCERN),
        "stakeholder_requirements": bool(requirements)
        and linked(EntityKind.REQUIREMENT, RelationPredicate.DERIVED_FROM, EntityKind.CONCERN),
        "lifecycle_analysis": has(EntityKind.LIFECYCLE_STAGE) and has(EntityKind.LIFECYCLE_TRANSITION),
        "scenario_exploration": has(EntityKind.SCENARIO_HYPOTHESIS),
        "use_case_analysis": has(EntityKind.USE_CASE),
        "operational_scenario": has(EntityKind.OPERATIONAL_SCENARIO)
        and linked(EntityKind.STAKEHOLDER, RelationPredicate.PARTICIPATES_IN, EntityKind.OPERATIONAL_SCENARIO),
        "activity_analysis": has(EntityKind.ACTIVITY),
        "system_requirement_derivation": any(
            item.payload.get("derived_by") == "system_requirement_derivation"
            for item in requirements
        ),
        "function_identification": bool(functions)
        and linked(EntityKind.REQUIREMENT, RelationPredicate.SATISFIED_BY, EntityKind.FUNCTION),
        "functional_decomposition": bool(functions)
        and all(str(item.payload.get("decomposition", "")).strip() for item in functions),
        "functional_interaction": has(EntityKind.FUNCTIONAL_FLOW)
        and linked(EntityKind.FUNCTION, RelationPredicate.EXCHANGES_WITH, EntityKind.FUNCTIONAL_FLOW),
        "functional_scenario": has(EntityKind.FUNCTIONAL_SCENARIO)
        and any(bool(item.payload.get("function_ids")) for item in active if item.kind is EntityKind.FUNCTIONAL_SCENARIO),
        "functional_requirement": bool(requirements)
        and all(bool(item.payload.get("functional_behavior_ids")) for item in requirements),
        "logical_analysis": has(EntityKind.LOGICAL_COMPONENT)
        and linked(EntityKind.FUNCTION, RelationPredicate.ALLOCATED_TO, EntityKind.LOGICAL_COMPONENT),
        "dependency_clustering": bool(functions)
        and has(EntityKind.LOGICAL_COMPONENT)
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
        "architecture_evaluation": has(EntityKind.LOGICAL_COMPONENT)
        and all(
            str(item.payload.get("cohesion", "")).strip()
            and str(item.payload.get("coupling", "")).strip()
            and str(item.payload.get("architecture_rationale", "")).strip()
            for item in active
            if item.kind is EntityKind.LOGICAL_COMPONENT
        ),
        "physical_candidates": has(EntityKind.PHYSICAL_BLOCK)
        and linked(EntityKind.LOGICAL_COMPONENT, RelationPredicate.ALLOCATED_TO, EntityKind.PHYSICAL_BLOCK),
        "allocation_tradeoff": bool(physicals)
        and all(bool(item.payload.get("trade_study")) for item in physicals),
        "technical_requirement": (
            linked(EntityKind.REQUIREMENT, RelationPredicate.SATISFIED_BY, EntityKind.PHYSICAL_BLOCK)
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
            for item in physicals
        ),
        "interface_sequence_state": has(EntityKind.INTERFACE)
        and has(EntityKind.STATE)
        and linked(EntityKind.LOGICAL_COMPONENT, RelationPredicate.CONNECTED_TO, EntityKind.INTERFACE)
        and linked(EntityKind.LOGICAL_COMPONENT, RelationPredicate.DECOMPOSES, EntityKind.STATE),
        "fmea_stpa_hazard": has(EntityKind.HAZARD)
        and has(EntityKind.FAILURE_MODE)
        and linked(EntityKind.HAZARD, RelationPredicate.CAUSES, EntityKind.FAILURE_MODE),
        "verification_validation": bool(requirements)
        and all(
            any(
                source_id == requirement.id
                and predicate is RelationPredicate.VERIFIED_BY
                for source_id, predicate, _target_id in relation_keys
            )
            and any(
                source_id == requirement.id
                and predicate is RelationPredicate.VALIDATED_BY
                for source_id, predicate, _target_id in relation_keys
            )
            for requirement in requirements
        ),
        "reverse_feasibility": bool(requirements)
        and any(bool(item.payload.get("feasibility_review")) for item in requirements),
        "global_cross_analysis": has(EntityKind.VERIFICATION_CASE)
        and all(
            item.payload.get("cross_analysis_status") == "checked"
            for item in active
            if item.kind is EntityKind.VERIFICATION_CASE
        ),
    }
    return bool(rules.get(task_id, True))


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
