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
    target_task: str = ""


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
        return RepairPlan(Phase.CLOSURE, (), "coverage is already saturated", "")
    phase = min((_PHASES[gap.root_cause] for gap in report.gaps), key=lambda item: list(Phase).index(item))
    operations: list[AddEntity] = []
    task_by_root = {
        "stakeholder": "stakeholder_analysis", "lifecycle": "lifecycle_analysis",
        "scenario": "scenario_exploration", "requirement": "stakeholder_requirements",
        "function": "function_identification", "architecture": "logical_analysis",
        "verification": "verification_validation", "evidence": "system_definition",
    }
    labels = {
        "stakeholder": "待确认的利益相关方", "lifecycle": "待确认的生命周期阶段",
        "scenario": "待确认的场景假设", "requirement": "待确认的系统需求",
        "function": "待确认的系统功能", "architecture": "待确认的逻辑架构候选",
        "verification": "待确认的验证用例", "evidence": "待补充的证据",
    }
    target_task = task_by_root[report.gaps[0].root_cause]
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
            labels[gap.root_cause],
            {"repair_code": gap.code, "requires_human_review": True},
            status=EntityStatus.CANDIDATE,
            producer=Producer.LLM,
            revision=revision,
        )
        operations.append(AddEntity(entity))
    return RepairPlan(phase, tuple(operations), "repair the smallest task root and re-run its gate", target_task)


def patch_for_plan(project_id: str, task_id: str, graph: ModelGraph, plan: RepairPlan) -> Patch:
    return Patch.create(project_id, task_id, plan.operations, plan.reason, graph.revision)
