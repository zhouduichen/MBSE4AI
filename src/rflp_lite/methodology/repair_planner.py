"""Deterministic root-cause classification and minimal RepairTask policies."""

from __future__ import annotations

from dataclasses import dataclass

from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.contracts import ContextQuery, CompletionCondition, FailureRoute, Phase, TaskSpec
from rflp_lite.methodology.policy import PatchPolicy
from rflp_lite.methodology.repair_context import RepairContext


_ROOT_CAUSES = {
    "missing_stakeholder": "missing_entity", "missing_lifecycle": "missing_entity",
    "missing_requirement": "missing_entity", "missing_function": "missing_entity",
    "missing_scenario": "missing_entity", "missing_use_case": "missing_entity",
    "incomplete_rflp_chain": "missing_entity_or_relation",
    "broken_requirement_function_trace": "missing_relation_or_function",
    "broken_requirement_rflp_trace": "missing_relation_or_allocation",
    "missing_verification": "missing_entity",
    "broken_requirement_verification_trace": "missing_relation_or_verification",
    "reference_missing": "invalid_relation", "relation_endpoint_invalid": "invalid_relation",
    "semantic_invalid": "invalid_entity_payload", "evidence_missing": "missing_evidence_reference",
    "patch_policy_violation": "invalid_entity_payload",
}


@dataclass(frozen=True, slots=True)
class RepairTask:
    id: str
    issue_code: str
    root_cause: str
    target_task_id: str
    writable_kinds: frozenset[EntityKind]
    allowed_predicates: frozenset[RelationPredicate]
    max_operations: int

    def as_task_spec(self, context: RepairContext) -> TaskSpec:
        input_kinds = frozenset(entity.kind for entity in context.local_entities)
        output_kinds = self.writable_kinds or frozenset(EntityKind)
        policy = PatchPolicy(
            writable_kinds=self.writable_kinds,
            writable_fields=frozenset({"name", "status", "confidence", "payload", "lifecycle_ids", "evidence_ids"}),
            allowed_predicates=self.allowed_predicates,
            allowed_entity_scope="context_and_outputs",
            max_operations=self.max_operations,
        )
        return TaskSpec(
            self.id,
            _phase_for_task(self.target_task_id),
            input_kinds,
            output_kinds,
            ContextQuery(input_kinds),
            f"{self.id}.v1",
            f"{self.id}.v1",
            validators=("schema", "identity", "reference", "evidence", "semantic", "patch_policy"),
            max_attempts=1,
            failure_routes=(FailureRoute("semantic_invalid", _phase_for_task(self.target_task_id)),),
            completion_condition=CompletionCondition(output_kinds),
            patch_policy=policy,
        )


def _phase_for_task(task_id: str) -> Phase:
    if task_id in {"function_identification"}:
        return Phase.FUNCTIONAL
    if task_id in {"logical_analysis", "physical_candidates"}:
        return Phase.LOGICAL_PHYSICAL
    if task_id in {"verification_validation"}:
        return Phase.ASSURANCE
    return Phase.OPERATIONAL


def classify_root_cause(issue_code: str) -> str:
    return _ROOT_CAUSES.get(issue_code, "invalid_entity_payload")


def plan(context: RepairContext) -> RepairTask:
    code = context.issue_code
    root_cause = classify_root_cause(code)
    if code in {"missing_function", "broken_requirement_function_trace"}:
        kinds, predicates, target, limit = frozenset({EntityKind.FUNCTION}), frozenset({RelationPredicate.SATISFIED_BY}), "function_identification", 4
    elif code in {"incomplete_rflp_chain", "broken_requirement_rflp_trace"}:
        kinds, predicates, target, limit = frozenset({EntityKind.LOGICAL_COMPONENT, EntityKind.PHYSICAL_BLOCK}), frozenset({RelationPredicate.ALLOCATED_TO, RelationPredicate.REALIZED_BY}), "logical_analysis", 4
    elif code in {"missing_verification", "broken_requirement_verification_trace"}:
        kinds, predicates, target, limit = frozenset({EntityKind.VERIFICATION_CASE}), frozenset({RelationPredicate.VERIFIED_BY}), "verification_validation", 3
    elif code == "missing_stakeholder":
        kinds, predicates, target, limit = frozenset({EntityKind.STAKEHOLDER}), frozenset(), "stakeholder_analysis", 2
    elif code == "missing_lifecycle":
        kinds, predicates, target, limit = frozenset({EntityKind.LIFECYCLE_STAGE}), frozenset(), "lifecycle_analysis", 2
    elif code in {"missing_scenario", "missing_use_case"}:
        kinds, predicates, target, limit = frozenset({EntityKind.SCENARIO_HYPOTHESIS, EntityKind.USE_CASE}), frozenset(), "scenario_exploration", 3
    elif code == "missing_requirement":
        kinds, predicates, target, limit = frozenset({EntityKind.REQUIREMENT}), frozenset(), "stakeholder_requirements", 2
    elif code in {"reference_missing", "relation_endpoint_invalid"}:
        kinds, predicates, target, limit = frozenset(), frozenset({RelationPredicate.SATISFIED_BY, RelationPredicate.ALLOCATED_TO, RelationPredicate.REALIZED_BY, RelationPredicate.VERIFIED_BY}), "", 2
    elif code == "missing_evidence_reference":
        kinds, predicates, target, limit = frozenset(), frozenset(), "system_definition", 1
    else:
        root_kind = next((entity.kind for entity in context.local_entities if entity.id in context.root_entity_ids), EntityKind.REQUIREMENT)
        kinds, predicates, target, limit = frozenset({root_kind}), frozenset(), "", 2
    return RepairTask(f"repair.{code}", code, root_cause, target, kinds, predicates, limit)
