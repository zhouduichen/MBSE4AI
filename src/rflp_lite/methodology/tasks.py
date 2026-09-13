"""Versioned TaskSpec catalog; task control flow lives in WorkflowRunner."""

from __future__ import annotations

from collections.abc import Iterable

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.contracts import CompletionCondition, ContextQuery, FailureAction, FailureRoute, Phase, TaskSpec
from rflp_lite.methodology.policy import PatchPolicy
from rflp_lite.methodology.proposal_compiler import proposal_schema


def _task(
    task_id: str,
    phase: Phase,
    input_kinds: set[EntityKind],
    output_kinds: set[EntityKind],
    *,
    template: str | None = None,
    completion_condition: CompletionCondition | None = None,
    allowed_predicates: Iterable[RelationPredicate] | None = None,
) -> TaskSpec:
    kinds = frozenset(input_kinds)
    routes = [FailureRoute("task_output_invalid", phase, FailureAction.RETRY, task_id)]
    if task_id == "function_identification":
        routes.append(FailureRoute("broken_requirement_function_trace", Phase.FUNCTIONAL, FailureAction.REPAIR, task_id))
    elif task_id == "logical_analysis":
        routes.extend((
            FailureRoute("incomplete_rflp_chain", Phase.LOGICAL_PHYSICAL, FailureAction.REPAIR, task_id),
            FailureRoute("broken_requirement_rflp_trace", Phase.LOGICAL_PHYSICAL, FailureAction.REPAIR, task_id),
        ))
    elif task_id == "verification_validation":
        routes.extend((
            FailureRoute("missing_verification", Phase.ASSURANCE, FailureAction.REPAIR, task_id),
            FailureRoute("broken_requirement_verification_trace", Phase.ASSURANCE, FailureAction.REPAIR, task_id),
            FailureRoute("missing_validation", Phase.ASSURANCE, FailureAction.REPAIR, task_id),
            FailureRoute("broken_requirement_validation_trace", Phase.ASSURANCE, FailureAction.REPAIR, task_id),
        ))
    return TaskSpec(
        task_id,
        phase,
        kinds,
        frozenset(output_kinds),
        ContextQuery(kinds),
        template or f"{phase.value}.{task_id}",
        f"{task_id}.v2",
        validators=("schema", "identity", "reference", "evidence", "semantic", "patch_policy"),
        max_attempts=2,
        failure_routes=tuple(routes),
        completion_condition=completion_condition or CompletionCondition(frozenset(output_kinds), 0),
        patch_policy=PatchPolicy.for_task(
            input_kinds,
            output_kinds,
            allowed_predicates=allowed_predicates,
        ),
    )


def task_catalog() -> tuple[TaskSpec, ...]:
    return (
        _task(
            "system_definition",
            Phase.OPERATIONAL,
            {EntityKind.SYSTEM},
            {EntityKind.SYSTEM},
            completion_condition=CompletionCondition(frozenset({EntityKind.SYSTEM}), 1),
            allowed_predicates=frozenset(),
        ),
        _task(
            "stakeholder_analysis",
            Phase.OPERATIONAL,
            {EntityKind.SYSTEM, EntityKind.STAKEHOLDER},
            {EntityKind.STAKEHOLDER, EntityKind.CONCERN},
            allowed_predicates={RelationPredicate.HAS_CONCERN},
        ),
        _task(
            "stakeholder_requirements",
            Phase.OPERATIONAL,
            {EntityKind.STAKEHOLDER, EntityKind.CONCERN, EntityKind.REQUIREMENT},
            {EntityKind.REQUIREMENT},
            allowed_predicates={RelationPredicate.DERIVED_FROM},
        ),
        _task("lifecycle_analysis", Phase.OPERATIONAL, {EntityKind.SYSTEM, EntityKind.STAKEHOLDER, EntityKind.LIFECYCLE_STAGE}, {EntityKind.LIFECYCLE_STAGE, EntityKind.LIFECYCLE_TRANSITION}),
        _task(
            "scenario_exploration",
            Phase.OPERATIONAL,
            {EntityKind.STAKEHOLDER, EntityKind.LIFECYCLE_STAGE, EntityKind.SCENARIO_HYPOTHESIS},
            {EntityKind.SCENARIO_HYPOTHESIS},
            allowed_predicates={RelationPredicate.DERIVED_FROM},
        ),
        _task("use_case_analysis", Phase.OPERATIONAL, {EntityKind.SCENARIO_HYPOTHESIS, EntityKind.STAKEHOLDER, EntityKind.USE_CASE}, {EntityKind.USE_CASE}),
        _task(
            "operational_scenario",
            Phase.OPERATIONAL,
            {EntityKind.USE_CASE, EntityKind.STAKEHOLDER, EntityKind.OPERATIONAL_SCENARIO},
            {EntityKind.OPERATIONAL_SCENARIO},
            allowed_predicates={
                RelationPredicate.DERIVED_FROM,
                RelationPredicate.PARTICIPATES_IN,
                RelationPredicate.OCCURS_IN,
            },
        ),
        _task("activity_analysis", Phase.OPERATIONAL, {EntityKind.OPERATIONAL_SCENARIO, EntityKind.ACTIVITY, EntityKind.REQUIREMENT, EntityKind.LIFECYCLE_STAGE}, {EntityKind.ACTIVITY}),
        _task("system_requirement_derivation", Phase.OPERATIONAL, {EntityKind.ACTIVITY, EntityKind.OPERATIONAL_SCENARIO, EntityKind.REQUIREMENT}, {EntityKind.REQUIREMENT}),
        _task("function_identification", Phase.FUNCTIONAL, {EntityKind.REQUIREMENT, EntityKind.USE_CASE, EntityKind.ACTIVITY}, {EntityKind.FUNCTION}),
        _task("functional_decomposition", Phase.FUNCTIONAL, {EntityKind.FUNCTION, EntityKind.REQUIREMENT}, {EntityKind.FUNCTION}),
        _task("functional_interaction", Phase.FUNCTIONAL, {EntityKind.FUNCTION, EntityKind.FUNCTIONAL_FLOW}, {EntityKind.FUNCTIONAL_FLOW}),
        _task("functional_scenario", Phase.FUNCTIONAL, {EntityKind.FUNCTION, EntityKind.FUNCTIONAL_SCENARIO}, {EntityKind.FUNCTIONAL_SCENARIO}),
        _task("functional_requirement", Phase.FUNCTIONAL, {EntityKind.FUNCTION, EntityKind.REQUIREMENT}, {EntityKind.REQUIREMENT}),
        _task("logical_analysis", Phase.LOGICAL_PHYSICAL, {EntityKind.FUNCTION, EntityKind.FUNCTIONAL_FLOW, EntityKind.REQUIREMENT}, {EntityKind.LOGICAL_COMPONENT}),
        _task("physical_candidates", Phase.LOGICAL_PHYSICAL, {EntityKind.LOGICAL_COMPONENT, EntityKind.REQUIREMENT, EntityKind.EVIDENCE}, {EntityKind.PHYSICAL_BLOCK}),
        _task("allocation_tradeoff", Phase.LOGICAL_PHYSICAL, {EntityKind.LOGICAL_COMPONENT, EntityKind.PHYSICAL_BLOCK}, {EntityKind.PHYSICAL_BLOCK}),
        _task("technical_requirement", Phase.LOGICAL_PHYSICAL, {EntityKind.FUNCTION, EntityKind.PHYSICAL_BLOCK, EntityKind.REQUIREMENT}, {EntityKind.REQUIREMENT, EntityKind.PHYSICAL_BLOCK}),
        _task("interface_sequence_state", Phase.ASSURANCE, {EntityKind.FUNCTION, EntityKind.LOGICAL_COMPONENT, EntityKind.INTERFACE, EntityKind.STATE}, {EntityKind.INTERFACE, EntityKind.STATE}),
        _task("fmea_stpa_hazard", Phase.ASSURANCE, {EntityKind.HAZARD, EntityKind.FAILURE_MODE, EntityKind.REQUIREMENT}, {EntityKind.HAZARD, EntityKind.FAILURE_MODE}),
        _task("verification_validation", Phase.ASSURANCE, {EntityKind.REQUIREMENT, EntityKind.OPERATIONAL_SCENARIO, EntityKind.VERIFICATION_CASE, EntityKind.VALIDATION_CASE}, {EntityKind.VERIFICATION_CASE, EntityKind.VALIDATION_CASE}),
        _task("reverse_feasibility", Phase.ASSURANCE, {EntityKind.FUNCTION, EntityKind.REQUIREMENT, EntityKind.LOGICAL_COMPONENT, EntityKind.PHYSICAL_BLOCK, EntityKind.VERIFICATION_CASE, EntityKind.VALIDATION_CASE}, {EntityKind.REQUIREMENT}),
        _task("global_cross_analysis", Phase.ASSURANCE, {EntityKind.REQUIREMENT, EntityKind.VERIFICATION_CASE, EntityKind.VALIDATION_CASE, EntityKind.HAZARD}, {EntityKind.VERIFICATION_CASE}),
    )


def tasks_for_phase(phase: Phase) -> tuple[TaskSpec, ...]:
    return tuple(task for task in task_catalog() if task.phase is phase)


def task_spec_hash(task: TaskSpec) -> str:
    policy = task.patch_policy
    return canonical_hash({
        "id": task.id, "phase": task.phase.value,
        "input_kinds": sorted(kind.value for kind in task.input_kinds),
        "output_kinds": sorted(kind.value for kind in task.output_kinds),
        "context_query": {
            "entity_kinds": sorted(kind.value for kind in task.context_query.entity_kinds),
            "neighborhood_hops": task.context_query.neighborhood_hops,
            "include_evidence": task.context_query.include_evidence,
        },
        "prompt_template_id": task.prompt_template_id,
        "output_schema_id": task.output_schema_id,
        "tools": task.tools, "validators": task.validators, "max_attempts": task.max_attempts,
        "failure_routes": tuple({
            "issue_code": route.issue_code,
            "rollback_phase": route.rollback_phase.value if route.rollback_phase else None,
            "action": route.action.value,
            "target_task_id": route.target_task_id,
        } for route in task.failure_routes),
        "completion_condition": {
            "required_output_kinds": sorted(kind.value for kind in task.completion_condition.required_output_kinds),
            "minimum_entities": task.completion_condition.minimum_entities,
            "require_accepted": task.completion_condition.require_accepted,
            "required_trace_rules": task.completion_condition.required_trace_rules,
        },
        "patch_policy": {
            "writable_kinds": sorted(kind.value for kind in policy.writable_kinds),
            "writable_fields": sorted(policy.writable_fields),
            "allowed_predicates": sorted(item.value for item in policy.allowed_predicates),
            "allowed_entity_scope": sorted(policy.allowed_entity_scope) if isinstance(policy.allowed_entity_scope, frozenset) else policy.allowed_entity_scope,
            "max_operations": policy.max_operations,
        },
    })


def output_contract(task: TaskSpec) -> dict[str, object]:
    """Return the semantic TaskProposal schema accepted from a task runtime."""

    payload_schemas = _payload_schemas()
    schema = proposal_schema(
        tuple(sorted(task.output_kinds, key=lambda kind: kind.value)),
        task.output_schema_id,
        payload_schemas,
        task.patch_policy,
    )
    if task.id == "system_definition":
        schema["properties"]["updates"]["items"]["properties"]["field_patch"]["properties"]["payload"] = dict(
            payload_schemas[EntityKind.SYSTEM.value]
        )
    schema["validators"] = list(task.validators)
    schema["max_attempts"] = task.max_attempts
    return schema


def _payload_schemas() -> dict[str, dict[str, object]]:
    return {
        EntityKind.SYSTEM.value: {
            "type": "object", "additionalProperties": False,
            "required": [
                "mission", "system_boundary", "objectives",
                "environment_assumptions", "exclusions", "open_questions",
            ],
            "properties": {
                "mission": {"type": "string", "minLength": 1},
                "system_boundary": {
                    "type": "object", "additionalProperties": False,
                    "required": ["inside", "outside"],
                    "properties": {
                        "inside": {"type": "array", "items": {"type": "string"}},
                        "outside": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "objectives": {"type": "array", "items": {"type": "string"}},
                "environment_assumptions": {"type": "array", "items": {"type": "string"}},
                "exclusions": {"type": "array", "items": {"type": "string"}},
                "open_questions": {"type": "array", "items": {"type": "string"}},
            },
        },
        EntityKind.REQUIREMENT.value: {
            "type": "object", "additionalProperties": False,
            "properties": {
                "statement": {"type": "string"},
                "level": {"enum": ["stakeholder", "system", "functional", "technical"]},
                "type": {"enum": ["functional", "performance", "interface", "safety", "constraint"]},
                "obligation": {"type": "string", "minLength": 1},
                "verification_method": {"type": "string", "minLength": 1},
                "rationale": {"type": "string"}, "source": {"type": "string"},
                "requires_human_review": {"type": "boolean"},
                "constraints": {"type": "object"},
                "constraint_provenance": {"type": "array"},
                "stakeholder_ids": {"type": "array", "items": {"type": "string"}},
                "derived_by": {"type": "string"},
                "functional_behavior_ids": {"type": "array", "items": {"type": "string"}},
                "functional_requirement_status": {"type": "string"},
                "source_requirement_ids": {"type": "array", "items": {"type": "string"}},
                "source_physical_ids": {"type": "array", "items": {"type": "string"}},
                "constraint_fields": {"type": "array", "items": {"type": "string"}},
                "open_questions": {"type": "array", "items": {"type": "string"}},
                "feasibility_review": {"type": "object"},
            },
        },
        EntityKind.CONCERN.value: {
            "type": "object", "additionalProperties": False,
            "properties": {
                "topic": {"type": "string", "minLength": 1},
                "stakeholder_ids": {"type": "array", "items": {"type": "string"}},
            },
        },
        EntityKind.STATE.value: {
            "type": "object", "additionalProperties": False,
            "properties": {
                "values": {"type": "array", "items": {"type": "string"}},
                "transitions": {"type": "array", "items": {"type": "string"}},
                "owner_id": {"type": "string"},
            },
        },
        EntityKind.OPERATIONAL_SCENARIO.value: {
            "type": "object", "additionalProperties": False,
            "properties": {
                "actor_ids": {"type": "array", "items": {"type": "string"}},
                "steps": {"type": "array"}, "exchanges": {"type": "array"},
                "internal_component_ids": {"type": "array", "items": {"type": "string"}},
            },
        },
        EntityKind.FUNCTIONAL_SCENARIO.value: {
            "type": "object", "additionalProperties": False,
            "properties": {"function_ids": {"type": "array", "items": {"type": "string"}}, "steps": {"type": "array"}},
        },
        EntityKind.VERIFICATION_CASE.value: {
            "type": "object", "additionalProperties": False,
            "properties": {
                "method": {"type": "string", "minLength": 1},
                "precondition": {"type": "string", "minLength": 1},
                "input": {"type": "string", "minLength": 1},
                "procedure": {"type": "string", "minLength": 1},
                "expected_result": {"type": "string", "minLength": 1},
                "pass_criteria": {"type": "string", "minLength": 1},
                "requirement_ids": {"type": "array", "items": {"type": "string"}},
                "scenario_ids": {"type": "array", "items": {"type": "string"}},
                "activity_ids": {"type": "array", "items": {"type": "string"}},
                "covered_branches": {"type": "array", "items": {"type": "string"}},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
                "cross_analysis_status": {"type": "string"},
                "traceability_checked": {"type": "boolean"},
            },
        },
        EntityKind.VALIDATION_CASE.value: {
            "type": "object", "additionalProperties": False,
            "properties": {
                "method": {"type": "string", "minLength": 1},
                "precondition": {"type": "string", "minLength": 1},
                "input": {"type": "string", "minLength": 1},
                "procedure": {"type": "string", "minLength": 1},
                "expected_result": {"type": "string", "minLength": 1},
                "pass_criteria": {"type": "string", "minLength": 1},
                "requirement_ids": {"type": "array", "items": {"type": "string"}},
                "scenario_ids": {"type": "array", "items": {"type": "string"}},
                "activity_ids": {"type": "array", "items": {"type": "string"}},
                "covered_branches": {"type": "array", "items": {"type": "string"}},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
            },
        },
        EntityKind.HAZARD.value: {
            "type": "object", "additionalProperties": False,
            "properties": {
                "description": {"type": "string", "minLength": 1},
                "requirement_ids": {"type": "array", "items": {"type": "string"}},
                "activity_ids": {"type": "array", "items": {"type": "string"}},
                "branches": {"type": "array", "items": {"type": "string"}},
            },
        },
        EntityKind.FAILURE_MODE.value: {
            "type": "object", "additionalProperties": False,
            "properties": {
                "effect": {"type": "string", "minLength": 1},
                "cause": {"type": "string", "minLength": 1},
                "requirement_ids": {"type": "array", "items": {"type": "string"}},
                "activity_ids": {"type": "array", "items": {"type": "string"}},
            },
        },
        EntityKind.PHYSICAL_BLOCK.value: {
            "type": "object", "additionalProperties": False,
            "properties": {
                "candidate_type": {"type": "string"}, "vendor": {"type": "string"},
                "part_number": {"type": "string"}, "constraints": {"type": ["array", "object"]},
                "constraint_provenance": {"type": "array"},
                "logical_id": {"type": "string"}, "measurement_status": {"type": "string"},
                "technical_requirement_status": {"type": "string"},
                "trade_study": {"type": "object"},
                "rationale": {"type": "string"},
            },
        },
    }
