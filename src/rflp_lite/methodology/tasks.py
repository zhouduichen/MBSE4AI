"""Versioned TaskSpec catalog; task control flow lives in WorkflowRunner."""

from __future__ import annotations

from rflp_lite.domain.entities import EntityKind
from rflp_lite.methodology.contracts import ContextQuery, Phase, TaskSpec


def _task(
    task_id: str,
    phase: Phase,
    input_kinds: set[EntityKind],
    output_kinds: set[EntityKind],
    *,
    template: str | None = None,
) -> TaskSpec:
    kinds = frozenset(input_kinds)
    return TaskSpec(
        task_id,
        phase,
        kinds,
        frozenset(output_kinds),
        ContextQuery(kinds),
        template or f"{phase.value}.{task_id}",
        f"{task_id}.v2",
        validators=("schema", "identity", "reference"),
    )


def task_catalog() -> tuple[TaskSpec, ...]:
    return (
        _task("system_definition", Phase.OPERATIONAL, {EntityKind.SYSTEM}, {EntityKind.SYSTEM}),
        _task("stakeholder_analysis", Phase.OPERATIONAL, {EntityKind.SYSTEM, EntityKind.STAKEHOLDER}, {EntityKind.STAKEHOLDER, EntityKind.CONCERN}),
        _task("stakeholder_requirements", Phase.OPERATIONAL, {EntityKind.STAKEHOLDER, EntityKind.CONCERN, EntityKind.REQUIREMENT}, {EntityKind.REQUIREMENT}),
        _task("lifecycle_analysis", Phase.OPERATIONAL, {EntityKind.SYSTEM, EntityKind.STAKEHOLDER, EntityKind.LIFECYCLE_STAGE}, {EntityKind.LIFECYCLE_STAGE, EntityKind.LIFECYCLE_TRANSITION}),
        _task("scenario_exploration", Phase.OPERATIONAL, {EntityKind.STAKEHOLDER, EntityKind.LIFECYCLE_STAGE, EntityKind.SCENARIO_HYPOTHESIS}, {EntityKind.SCENARIO_HYPOTHESIS}),
        _task("use_case_analysis", Phase.OPERATIONAL, {EntityKind.SCENARIO_HYPOTHESIS, EntityKind.STAKEHOLDER, EntityKind.USE_CASE}, {EntityKind.USE_CASE}),
        _task("operational_scenario", Phase.OPERATIONAL, {EntityKind.USE_CASE, EntityKind.STAKEHOLDER, EntityKind.OPERATIONAL_SCENARIO}, {EntityKind.OPERATIONAL_SCENARIO}),
        _task("activity_analysis", Phase.OPERATIONAL, {EntityKind.OPERATIONAL_SCENARIO, EntityKind.ACTIVITY, EntityKind.REQUIREMENT}, {EntityKind.ACTIVITY}),
        _task("system_requirement_derivation", Phase.OPERATIONAL, {EntityKind.ACTIVITY, EntityKind.OPERATIONAL_SCENARIO, EntityKind.REQUIREMENT}, {EntityKind.REQUIREMENT}),
        _task("function_identification", Phase.FUNCTIONAL, {EntityKind.REQUIREMENT, EntityKind.USE_CASE, EntityKind.ACTIVITY}, {EntityKind.FUNCTION}),
        _task("functional_decomposition", Phase.FUNCTIONAL, {EntityKind.FUNCTION, EntityKind.REQUIREMENT}, {EntityKind.FUNCTION}),
        _task("functional_interaction", Phase.FUNCTIONAL, {EntityKind.FUNCTION, EntityKind.FUNCTIONAL_FLOW}, {EntityKind.FUNCTIONAL_FLOW}),
        _task("functional_scenario", Phase.FUNCTIONAL, {EntityKind.FUNCTION, EntityKind.FUNCTIONAL_SCENARIO}, {EntityKind.FUNCTIONAL_SCENARIO}),
        _task("functional_requirement", Phase.FUNCTIONAL, {EntityKind.FUNCTION, EntityKind.REQUIREMENT}, {EntityKind.REQUIREMENT}),
        _task("logical_analysis", Phase.LOGICAL_PHYSICAL, {EntityKind.FUNCTION, EntityKind.FUNCTIONAL_FLOW, EntityKind.REQUIREMENT}, {EntityKind.LOGICAL_COMPONENT}),
        _task("physical_candidates", Phase.LOGICAL_PHYSICAL, {EntityKind.LOGICAL_COMPONENT, EntityKind.REQUIREMENT, EntityKind.EVIDENCE}, {EntityKind.PHYSICAL_BLOCK}),
        _task("allocation_tradeoff", Phase.LOGICAL_PHYSICAL, {EntityKind.LOGICAL_COMPONENT, EntityKind.PHYSICAL_BLOCK}, {EntityKind.PHYSICAL_BLOCK}),
        _task("technical_requirement", Phase.LOGICAL_PHYSICAL, {EntityKind.PHYSICAL_BLOCK, EntityKind.REQUIREMENT}, {EntityKind.REQUIREMENT}),
        _task("interface_sequence_state", Phase.ASSURANCE, {EntityKind.FUNCTION, EntityKind.LOGICAL_COMPONENT, EntityKind.INTERFACE, EntityKind.STATE}, {EntityKind.INTERFACE, EntityKind.STATE}),
        _task("fmea_stpa_hazard", Phase.ASSURANCE, {EntityKind.HAZARD, EntityKind.FAILURE_MODE, EntityKind.REQUIREMENT}, {EntityKind.HAZARD, EntityKind.FAILURE_MODE}),
        _task("verification_validation", Phase.ASSURANCE, {EntityKind.REQUIREMENT, EntityKind.OPERATIONAL_SCENARIO, EntityKind.VERIFICATION_CASE, EntityKind.VALIDATION_CASE}, {EntityKind.VERIFICATION_CASE, EntityKind.VALIDATION_CASE}),
        _task("reverse_feasibility", Phase.ASSURANCE, {EntityKind.REQUIREMENT, EntityKind.LOGICAL_COMPONENT, EntityKind.PHYSICAL_BLOCK}, {EntityKind.REQUIREMENT}),
        _task("global_cross_analysis", Phase.ASSURANCE, {EntityKind.REQUIREMENT, EntityKind.VERIFICATION_CASE, EntityKind.HAZARD}, {EntityKind.VERIFICATION_CASE}),
    )


def tasks_for_phase(phase: Phase) -> tuple[TaskSpec, ...]:
    return tuple(task for task in task_catalog() if task.phase is phase)


def output_contract(task: TaskSpec) -> dict[str, object]:
    """Return the single bounded JSON envelope accepted from a task runtime.

    The runtime intentionally accepts operations instead of a free-form
    analysis dictionary.  This keeps the LLM useful for proposal generation
    while leaving identity, relation typing, lock checks, and CAS semantics in
    the domain/application layers.
    """

    kind_values = [kind.value for kind in task.output_kinds]
    operation = {
        "type": "object",
        "additionalProperties": False,
        "required": ["op"],
        "properties": {
            "op": {"enum": ["ADD", "UPDATE", "RELATE", "DEPRECATE"]},
            "kind": {"enum": kind_values},
            "name": {"type": "string", "minLength": 1},
            "entity_id": {"type": "string"},
            "source_id": {"type": "string"},
            "target_id": {"type": "string"},
            "predicate": {"type": "string"},
            "payload": {"type": "object"},
            "field_patch": {"type": "object"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "source_ids": {"type": "array", "items": {"type": "string"}},
            "lifecycle_ids": {"type": "array", "items": {"type": "string"}},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["operations"],
        "properties": {
            "operations": {"type": "array", "items": operation, "maxItems": 32},
            "reason": {"type": "string", "maxLength": 300},
        },
    }
