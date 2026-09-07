"""Versioned TaskSpec catalog; task control flow lives in WorkflowRunner."""

from __future__ import annotations

from rflp_lite.domain.entities import EntityKind
from rflp_lite.methodology.contracts import CompletionCondition, ContextQuery, Phase, TaskSpec


def task_catalog() -> tuple[TaskSpec, ...]:
    return (
        TaskSpec(
            "system_definition", Phase.OPERATIONAL, frozenset({EntityKind.SYSTEM}),
            frozenset({EntityKind.SYSTEM}), ContextQuery(frozenset({EntityKind.SYSTEM}), 0),
            "operational.system_definition", "system-definition.v2",
            validators=("schema", "identity"),
        ),
        TaskSpec(
            "stakeholder_analysis", Phase.OPERATIONAL, frozenset({EntityKind.SYSTEM, EntityKind.STAKEHOLDER}),
            frozenset({EntityKind.STAKEHOLDER, EntityKind.CONCERN}),
            ContextQuery(frozenset({EntityKind.SYSTEM, EntityKind.STAKEHOLDER})),
            "operational.stakeholder_analysis", "stakeholder.v2", validators=("schema", "identity", "reference"),
        ),
        TaskSpec(
            "lifecycle_analysis", Phase.OPERATIONAL, frozenset({EntityKind.SYSTEM, EntityKind.STAKEHOLDER, EntityKind.LIFECYCLE_STAGE}),
            frozenset({EntityKind.LIFECYCLE_STAGE, EntityKind.LIFECYCLE_TRANSITION}),
            ContextQuery(frozenset({EntityKind.SYSTEM, EntityKind.STAKEHOLDER, EntityKind.LIFECYCLE_STAGE})),
            "operational.lifecycle_analysis", "lifecycle.v2", validators=("schema", "lifecycle"),
        ),
        TaskSpec(
            "scenario_exploration", Phase.OPERATIONAL,
            frozenset({EntityKind.STAKEHOLDER, EntityKind.LIFECYCLE_STAGE, EntityKind.SCENARIO_HYPOTHESIS}),
            frozenset({EntityKind.SCENARIO_HYPOTHESIS, EntityKind.USE_CASE}),
            ContextQuery(frozenset({EntityKind.STAKEHOLDER, EntityKind.LIFECYCLE_STAGE, EntityKind.SCENARIO_HYPOTHESIS})),
            "operational.scenario_exploration", "scenario-hypothesis.v2", validators=("schema", "coverage"),
        ),
        TaskSpec(
            "functional_identification", Phase.FUNCTIONAL,
            frozenset({EntityKind.REQUIREMENT, EntityKind.USE_CASE, EntityKind.ACTIVITY}),
            frozenset({EntityKind.FUNCTION, EntityKind.FUNCTIONAL_FLOW}),
            ContextQuery(frozenset({EntityKind.REQUIREMENT, EntityKind.USE_CASE, EntityKind.ACTIVITY})),
            "functional.identification", "function.v2", validators=("schema", "reference", "functional"),
        ),
        TaskSpec(
            "logical_analysis", Phase.LOGICAL_PHYSICAL,
            frozenset({EntityKind.FUNCTION, EntityKind.FUNCTIONAL_FLOW, EntityKind.REQUIREMENT}),
            frozenset({EntityKind.LOGICAL_COMPONENT}),
            ContextQuery(frozenset({EntityKind.FUNCTION, EntityKind.FUNCTIONAL_FLOW, EntityKind.REQUIREMENT})),
            "logical.analysis", "logical-component.v2", validators=("schema", "reference", "rflp"),
        ),
        TaskSpec(
            "physical_candidates", Phase.LOGICAL_PHYSICAL,
            frozenset({EntityKind.LOGICAL_COMPONENT, EntityKind.REQUIREMENT, EntityKind.EVIDENCE}),
            frozenset({EntityKind.PHYSICAL_BLOCK}),
            ContextQuery(frozenset({EntityKind.LOGICAL_COMPONENT, EntityKind.REQUIREMENT, EntityKind.EVIDENCE})),
            "physical.candidates", "physical-block.v2", validators=("schema", "reference", "rflp"),
        ),
        TaskSpec(
            "verification_validation", Phase.ASSURANCE,
            frozenset({EntityKind.REQUIREMENT, EntityKind.FUNCTION, EntityKind.SCENARIO_HYPOTHESIS, EntityKind.OPERATIONAL_SCENARIO}),
            frozenset({EntityKind.VERIFICATION_CASE, EntityKind.VALIDATION_CASE}),
            ContextQuery(frozenset({EntityKind.REQUIREMENT, EntityKind.FUNCTION, EntityKind.SCENARIO_HYPOTHESIS, EntityKind.OPERATIONAL_SCENARIO})),
            "assurance.verification_validation", "verification-case.v2", validators=("schema", "reference", "verification"),
        ),
    )


def tasks_for_phase(phase: Phase) -> tuple[TaskSpec, ...]:
    return tuple(task for task in task_catalog() if task.phase is phase)
