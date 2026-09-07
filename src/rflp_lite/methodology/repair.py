"""Local Patch repair planning for Coverage and Gate failures."""

from __future__ import annotations

from dataclasses import dataclass

from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.model import AddEntity, ModelGraph, Patch
from rflp_lite.methodology.contracts import Phase
from rflp_lite.methodology.coverage import CoverageGap, CoverageReport


@dataclass(frozen=True, slots=True)
class RepairPlan:
    rollback_phase: Phase
    operations: tuple[AddEntity, ...]
    reason: str


_PHASES = {
    "stakeholder": Phase.OPERATIONAL,
    "lifecycle": Phase.OPERATIONAL,
    "scenario": Phase.OPERATIONAL,
    "requirement": Phase.OPERATIONAL,
    "function": Phase.FUNCTIONAL,
    "architecture": Phase.LOGICAL_PHYSICAL,
    "verification": Phase.ASSURANCE,
    "evidence": Phase.OPERATIONAL,
}


def plan_repair(report: CoverageReport, *, revision: int = 0) -> RepairPlan:
    if not report.gaps:
        return RepairPlan(Phase.CLOSURE, (), "coverage is already saturated")
    phase = min((_PHASES[gap.root_cause] for gap in report.gaps), key=lambda item: list(Phase).index(item))
    operations: list[AddEntity] = []
    for gap in report.gaps:
        kind = {
            "stakeholder": EntityKind.STAKEHOLDER,
            "lifecycle": EntityKind.LIFECYCLE_STAGE,
            "scenario": EntityKind.SCENARIO_HYPOTHESIS,
            "requirement": EntityKind.REQUIREMENT,
            "function": EntityKind.FUNCTION,
            "architecture": EntityKind.LOGICAL_COMPONENT,
            "verification": EntityKind.VERIFICATION_CASE,
            "evidence": EntityKind.EVIDENCE,
        }[gap.root_cause]
        entity = make_entity(
            kind,
            f"{gap.code} 候选",
            {"gap_code": gap.code, "requires_human_review": True},
            status=EntityStatus.CANDIDATE,
            producer=Producer.LLM,
            revision=revision,
        )
        operations.append(AddEntity(entity))
    return RepairPlan(phase, tuple(operations), "repair coverage gaps with local candidate patches")


def patch_for_plan(project_id: str, task_id: str, graph: ModelGraph, plan: RepairPlan) -> Patch:
    return Patch.create(project_id, task_id, plan.operations, plan.reason, graph.revision)
