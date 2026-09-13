"""Product-level five-stage RFLP generation contracts.

The legacy catalog contains fine-grained methodology tasks.  This module
defines the smaller contracts used by the default product path so the LLM can
move a real model from requirements through assurance without exposing the
whole task catalog as one giant interaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.contracts import ContextQuery, Phase, TaskSpec
from rflp_lite.methodology.policy import PatchPolicy


class VerticalStage(StrEnum):
    REQUIREMENTS = "requirements"
    FUNCTIONAL = "functional"
    LOGICAL = "logical"
    PHYSICAL = "physical"
    VERIFICATION_VALIDATION = "verification_validation"


@dataclass(frozen=True, slots=True)
class VerticalStageSpec:
    stage: VerticalStage
    phase: Phase
    input_kinds: frozenset[EntityKind]
    output_kinds: frozenset[EntityKind]
    allowed_predicates: frozenset[RelationPredicate]
    required_kinds: frozenset[EntityKind]
    reasoning_tasks: tuple[str, ...] = ()


_ALL = frozenset(EntityKind)
_STAGES: tuple[VerticalStageSpec, ...] = (
    VerticalStageSpec(
        VerticalStage.REQUIREMENTS,
        Phase.OPERATIONAL,
        _ALL,
        frozenset({
            EntityKind.SYSTEM,
            EntityKind.STAKEHOLDER,
            EntityKind.CONCERN,
            EntityKind.LIFECYCLE_STAGE,
            EntityKind.SCENARIO_HYPOTHESIS,
            EntityKind.USE_CASE,
            EntityKind.OPERATIONAL_SCENARIO,
            EntityKind.ACTIVITY,
            EntityKind.REQUIREMENT,
        }),
        frozenset({
            RelationPredicate.HAS_CONCERN,
            RelationPredicate.PARTICIPATES_IN,
            RelationPredicate.OCCURS_IN,
            RelationPredicate.DERIVED_FROM,
            RelationPredicate.DECOMPOSES,
        }),
        frozenset({
            EntityKind.SYSTEM,
            EntityKind.STAKEHOLDER,
            EntityKind.LIFECYCLE_STAGE,
            EntityKind.SCENARIO_HYPOTHESIS,
            EntityKind.USE_CASE,
            EntityKind.OPERATIONAL_SCENARIO,
            EntityKind.ACTIVITY,
            EntityKind.REQUIREMENT,
        }),
        (
            "system_definition", "stakeholder_analysis", "stakeholder_requirements",
            "lifecycle_analysis", "scenario_exploration", "use_case_analysis",
            "operational_scenario", "activity_analysis", "system_requirement_derivation",
        ),
    ),
    VerticalStageSpec(
        VerticalStage.FUNCTIONAL,
        Phase.FUNCTIONAL,
        frozenset({
            EntityKind.SYSTEM,
            EntityKind.REQUIREMENT,
            EntityKind.OPERATIONAL_SCENARIO,
            EntityKind.ACTIVITY,
            EntityKind.FUNCTION,
            EntityKind.FUNCTIONAL_FLOW,
            EntityKind.FUNCTIONAL_SCENARIO,
        }),
        frozenset({
            EntityKind.FUNCTION,
            EntityKind.FUNCTIONAL_FLOW,
            EntityKind.FUNCTIONAL_SCENARIO,
        }),
        frozenset({
            RelationPredicate.SATISFIED_BY,
            RelationPredicate.DECOMPOSES,
            RelationPredicate.DERIVED_FROM,
            RelationPredicate.EXCHANGES_WITH,
        }),
        frozenset({EntityKind.FUNCTION}),
        (
            "function_identification", "functional_decomposition", "functional_interaction",
            "functional_scenario", "functional_requirement",
        ),
    ),
    VerticalStageSpec(
        VerticalStage.LOGICAL,
        Phase.LOGICAL_PHYSICAL,
        frozenset({
            EntityKind.SYSTEM,
            EntityKind.REQUIREMENT,
            EntityKind.FUNCTION,
            EntityKind.FUNCTIONAL_FLOW,
            EntityKind.LOGICAL_COMPONENT,
            EntityKind.INTERFACE,
        }),
        frozenset({EntityKind.LOGICAL_COMPONENT, EntityKind.INTERFACE}),
        frozenset({
            RelationPredicate.ALLOCATED_TO,
            RelationPredicate.EXCHANGES_WITH,
            RelationPredicate.CONNECTED_TO,
            RelationPredicate.DERIVED_FROM,
        }),
        frozenset({EntityKind.LOGICAL_COMPONENT}),
        (
            "logical_analysis", "interface_sequence_state",
            "dependency_clustering", "architecture_evaluation",
        ),
    ),
    VerticalStageSpec(
        VerticalStage.PHYSICAL,
        Phase.LOGICAL_PHYSICAL,
        frozenset({
            EntityKind.SYSTEM,
            EntityKind.REQUIREMENT,
            EntityKind.FUNCTION,
            EntityKind.LOGICAL_COMPONENT,
            EntityKind.PHYSICAL_BLOCK,
            EntityKind.EVIDENCE,
        }),
        frozenset({EntityKind.PHYSICAL_BLOCK, EntityKind.REQUIREMENT}),
        frozenset({
            RelationPredicate.ALLOCATED_TO,
            RelationPredicate.SATISFIED_BY,
            RelationPredicate.DERIVED_FROM,
        }),
        frozenset({EntityKind.PHYSICAL_BLOCK}),
        (
            "physical_candidates", "allocation_tradeoff", "technical_requirement",
            "constraint_propagation", "feasibility_selection",
        ),
    ),
    VerticalStageSpec(
        VerticalStage.VERIFICATION_VALIDATION,
        Phase.ASSURANCE,
        _ALL,
        frozenset({EntityKind.VERIFICATION_CASE, EntityKind.VALIDATION_CASE}),
        frozenset({
            RelationPredicate.VERIFIED_BY,
            RelationPredicate.VALIDATED_BY,
            RelationPredicate.SUPPORTED_BY,
        }),
        frozenset({EntityKind.VERIFICATION_CASE, EntityKind.VALIDATION_CASE}),
        (
            "fmea_stpa_hazard", "verification_validation", "reverse_feasibility",
            "global_cross_analysis",
        ),
    ),
)


def vertical_stage_specs() -> tuple[VerticalStageSpec, ...]:
    return _STAGES


def stage_spec(stage: VerticalStage | str) -> VerticalStageSpec:
    requested = VerticalStage(stage)
    return next(item for item in _STAGES if item.stage is requested)


def stage_task(stage: VerticalStage | str) -> TaskSpec:
    spec = stage_spec(stage)
    task_id = f"vertical.{spec.stage.value}"
    return TaskSpec(
        task_id,
        spec.phase,
        spec.input_kinds,
        spec.output_kinds,
        ContextQuery(spec.input_kinds, neighborhood_hops=1, include_evidence=True),
        task_id,
        f"{task_id}.v1",
        validators=("schema", "identity", "reference", "semantic", "patch_policy"),
        max_attempts=2,
        patch_policy=PatchPolicy.for_task(
            spec.input_kinds,
            spec.output_kinds,
            allowed_predicates=spec.allowed_predicates,
        ),
    )


def stage_required_kinds(stage: VerticalStage | str) -> frozenset[EntityKind]:
    return stage_spec(stage).required_kinds
