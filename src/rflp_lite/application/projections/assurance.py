"""Verification, validation, safety, FMEA, gate, and repair projections."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping

from rflp_lite.application.projections.common import entity_card, header, issues_by_entity
from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.contracts import Phase
from rflp_lite.methodology.coverage_matrix import build_requirement_coverage
from rflp_lite.methodology.gates import gate_for_phase
from rflp_lite.methodology.vv_contract import VV_PLAN_FIELDS, missing_vv_plan_fields


_GATE_LABELS = {
    "O-Gate": "运行场景质量门禁",
    "F-Gate": "功能质量门禁",
    "P-Gate": "逻辑与物理质量门禁",
    "Global-Gate": "全局质量门禁",
}
_PHASE_LABELS = {
    Phase.OPERATIONAL.value: "运行场景",
    Phase.FUNCTIONAL.value: "功能分析",
    Phase.LOGICAL_PHYSICAL.value: "逻辑与物理架构",
    Phase.ASSURANCE.value: "验证与确认",
}


@dataclass(frozen=True, slots=True)
class GateSummaryView:
    gate_id: str
    phase: str
    passed: bool
    checks: tuple[Mapping[str, object], ...]
    blocking_issues: tuple[Mapping[str, object], ...]
    coverage_summary: Mapping[str, object]
    rollback_phase: str | None
    gate_label: str = ""
    phase_label: str = ""
    status_label: str = ""

    def as_dict(self) -> Mapping[str, object]:
        return asdict(self)


def _gate(graph: ModelGraph, phase: Phase, issues: tuple[Mapping[str, object], ...], issue_index: Mapping[str, tuple[Mapping[str, object], ...]]) -> GateSummaryView:
    result = gate_for_phase(phase, graph)
    blocking = []
    for issue in result.issues:
        entity_ids = tuple(issue.entity_ids)
        if not entity_ids:
            blocking.append({"id": f"gate-{result.gate_id}-{issue.code}", "code": issue.code, "severity": "error", "entity_ids": [], "suggested_rollback": result.rollback_phase.value if result.rollback_phase else None, "status": "open"})
        for entity_id in entity_ids:
            blocking.extend(issue_index.get(entity_id, ()) or ({"id": f"gate-{result.gate_id}-{entity_id}", "code": issue.code, "severity": "error", "entity_ids": list(entity_ids), "suggested_rollback": result.rollback_phase.value if result.rollback_phase else None, "status": "open"},))
    flattened = blocking
    coverage = build_requirement_coverage(graph).metrics
    return GateSummaryView(
        result.gate_id,
        phase.value,
        result.passed,
        tuple(result.checks),
        tuple(flattened),
        dict(coverage),
        result.rollback_phase.value if result.rollback_phase else None,
        _GATE_LABELS.get(result.gate_id, result.gate_id),
        _PHASE_LABELS.get(phase.value, phase.value),
        "已通过" if result.passed else "需要处理",
    )


def build_assurance_view(graph: ModelGraph, issues: tuple[Mapping[str, object], ...] = ()) -> Mapping[str, object]:
    issue_index = issues_by_entity(issues)
    verification = {item.id: item for item in graph.entities if item.kind is EntityKind.VERIFICATION_CASE}
    validation = {item.id: item for item in graph.entities if item.kind is EntityKind.VALIDATION_CASE}
    vv_rows = []
    for requirement in sorted((item for item in graph.entities if item.kind is EntityKind.REQUIREMENT), key=lambda item: item.id):
        for kind, cases_by_id, predicate, code, label in (
            ("verification", verification, "verifiedBy", "MISSING_VERIFICATION", "验证"),
            ("validation", validation, "validatedBy", "MISSING_VALIDATION", "确认"),
        ):
            cases = [relation.target_id for relation in graph.relations if relation.source_id == requirement.id and relation.target_id in cases_by_id and relation.predicate.value == predicate]
            for case_id in sorted(cases) or [None]:
                case = cases_by_id.get(case_id) if case_id else None
                plan_fields = {
                    field: case.payload.get(field, "") if case else ""
                    for field in VV_PLAN_FIELDS
                }
                plan_missing = list(missing_vv_plan_fields(case.payload)) if case else [kind]
                plan_complete = bool(case and not plan_missing)
                vv_rows.append({
                    "requirement_id": requirement.id,
                    "requirement": requirement.meta.name,
                    "case_type": kind,
                    "case_type_label": label,
                    "case_id": case_id,
                    "method": case.payload.get("method", "") if case else "",
                    **plan_fields,
                    "missing_plan_fields": plan_missing,
                    "verification_case_id": case_id if kind == "verification" else None,
                    "validation_case_id": case_id if kind == "validation" else None,
                    "verification_case": case.meta.name if kind == "verification" and case else "",
                    "validation_case": case.meta.name if kind == "validation" and case else "",
                    "pass_criteria": case.payload.get("pass_criteria", "") if case else "",
                    "status": "PASS" if plan_complete else code,
                    "plan_status": "PASS" if plan_complete else code,
                    "execution_status": case.payload.get("execution_status", "pending") if case else "missing",
                    "execution_evidence_ids": list(case.payload.get("execution_evidence_ids", ())) if case and isinstance(case.payload.get("execution_evidence_ids", ()), (list, tuple)) else [],
                    "last_execution": case.payload.get("last_execution", {}) if case else {},
                    "issues": list(issue_index.get(requirement.id, ())),
                })
    hazards = []
    for hazard in sorted((item for item in graph.entities if item.kind is EntityKind.HAZARD), key=lambda item: item.id):
        hazards.append({**entity_card(hazard, issue_count=len(issue_index.get(hazard.id, ()))), "causes": [relation.source_id for relation in graph.relations if relation.target_id == hazard.id and relation.predicate.value == "causes"], "mitigations": [relation.target_id for relation in graph.relations if relation.source_id == hazard.id and relation.predicate.value == "mitigatedBy"], "verification": [relation.target_id for relation in graph.relations if relation.source_id == hazard.id and relation.predicate.value in {"mitigatedBy", "verifiedBy"}]})
    failure_modes = [entity_card(item, issue_count=len(issue_index.get(item.id, ()))) for item in sorted(graph.entities, key=lambda value: value.id) if item.kind is EntityKind.FAILURE_MODE]
    phases = (Phase.OPERATIONAL, Phase.FUNCTIONAL, Phase.LOGICAL_PHYSICAL, Phase.ASSURANCE)
    gates = [_gate(graph, phase, issues, issue_index).as_dict() for phase in phases]
    return {**header(graph).as_dict(), "verification_validation": vv_rows, "hazards": hazards, "failure_modes": failure_modes, "gates": gates, "repair_issues": [dict(issue) for issue in issues]}
