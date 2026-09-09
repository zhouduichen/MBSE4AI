"""Deterministic offline runtime used when no model profile is configured."""

from __future__ import annotations

from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.model import AddEntity, Patch, Relate
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.contracts import StepStatus, TaskExecutionRequest, TaskExecutionResponse


_PRIMARY_OUTPUT: dict[str, EntityKind] = {
    "system_definition": EntityKind.SYSTEM,
    "stakeholder_analysis": EntityKind.CONCERN,
    "stakeholder_requirements": EntityKind.REQUIREMENT,
    "lifecycle_analysis": EntityKind.LIFECYCLE_STAGE,
    "scenario_exploration": EntityKind.SCENARIO_HYPOTHESIS,
    "use_case_analysis": EntityKind.USE_CASE,
    "operational_scenario": EntityKind.OPERATIONAL_SCENARIO,
    "activity_analysis": EntityKind.ACTIVITY,
    "system_requirement_derivation": EntityKind.REQUIREMENT,
    "function_identification": EntityKind.FUNCTION,
    "functional_decomposition": EntityKind.FUNCTION,
    "functional_interaction": EntityKind.FUNCTIONAL_FLOW,
    "functional_scenario": EntityKind.FUNCTIONAL_SCENARIO,
    "functional_requirement": EntityKind.REQUIREMENT,
    "logical_analysis": EntityKind.LOGICAL_COMPONENT,
    "physical_candidates": EntityKind.PHYSICAL_BLOCK,
    "allocation_tradeoff": EntityKind.PHYSICAL_BLOCK,
    "technical_requirement": EntityKind.REQUIREMENT,
    "interface_sequence_state": EntityKind.INTERFACE,
    "fmea_stpa_hazard": EntityKind.HAZARD,
    "verification_validation": EntityKind.VERIFICATION_CASE,
    "reverse_feasibility": EntityKind.REQUIREMENT,
    "global_cross_analysis": EntityKind.VALIDATION_CASE,
}


def _first(context, kind: EntityKind):
    return next((item for item in context.entities if item.kind is kind), None)


class RuleRuntime:
    """Create reviewable candidates from context without inventing source facts."""

    def execute(self, request: TaskExecutionRequest) -> TaskExecutionResponse:
        kind = _PRIMARY_OUTPUT.get(request.task_id)
        if kind is None or kind.value not in {str(value) for value in request.output_contract.get("output_kinds", ())}:
            return TaskExecutionResponse(StepStatus.COMPLETED, diagnostics=("offline:no-op",))
        name = f"{request.task_id} 候选"
        existing = next((item for item in request.context_bundle.entities if item.kind is kind and item.meta.name == name), None)
        if existing is not None:
            return TaskExecutionResponse(StepStatus.COMPLETED, diagnostics=("offline:idempotent",))
        payload: dict[str, object] = {"task_id": request.task_id, "requires_human_review": True}
        if kind is EntityKind.REQUIREMENT:
            payload.update({"level": "system", "type": "functional", "obligation": "待确认", "verification_method": "review"})
        if kind is EntityKind.VERIFICATION_CASE:
            payload.update({"method": "review", "pass_criteria": "待确认的通过准则"})
        if kind is EntityKind.OPERATIONAL_SCENARIO:
            payload.update({"actor_ids": [item.id for item in request.context_bundle.entities if item.kind is EntityKind.STAKEHOLDER], "exchanges": [], "steps": [], "internal_component_ids": []})
        entity = make_entity(kind, name, payload, status=EntityStatus.CANDIDATE, producer=Producer.RULE, confidence=0.5, revision=request.context_bundle.revision)
        operations: list[object] = [AddEntity(entity)]
        context = request.context_bundle
        requirements = [item for item in context.entities if item.kind is EntityKind.REQUIREMENT]
        functions = [item for item in context.entities if item.kind is EntityKind.FUNCTION]
        logical = _first(context, EntityKind.LOGICAL_COMPONENT)
        if kind is EntityKind.FUNCTION:
            operations.extend(Relate(item.id, RelationPredicate.SATISFIED_BY, entity.id) for item in requirements)
        elif kind is EntityKind.LOGICAL_COMPONENT:
            operations.extend(Relate(item.id, RelationPredicate.ALLOCATED_TO, entity.id) for item in functions)
        elif kind is EntityKind.PHYSICAL_BLOCK and logical:
            operations.append(Relate(logical.id, RelationPredicate.ALLOCATED_TO, entity.id))
        elif kind is EntityKind.VERIFICATION_CASE:
            operations.extend(Relate(item.id, RelationPredicate.VERIFIED_BY, entity.id) for item in requirements)
        elif kind is EntityKind.INTERFACE:
            operations.extend(Relate(item.id, RelationPredicate.EXCHANGES_WITH, entity.id) for item in functions)
        elif kind is EntityKind.OPERATIONAL_SCENARIO:
            operations.extend(
                Relate(item.id, RelationPredicate.PARTICIPATES_IN, entity.id)
                for item in context.entities if item.kind is EntityKind.STAKEHOLDER
            )
        patch = Patch.create(context.project_id, request.task_id, tuple(operations), f"离线规则生成 {kind.value} 候选", context.revision)
        return TaskExecutionResponse(StepStatus.COMPLETED, patch=patch, diagnostics=("offline:rule-runtime",))
