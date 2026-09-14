"""Systems-engineering controller policy over Methodology Engine feedback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.engine import MethodologyEngine, MethodologyFinding, MethodologyReport


_TASK_TO_STAGE = {
    "system_definition": "requirements",
    "stakeholder_analysis": "requirements",
    "stakeholder_requirements": "requirements",
    "lifecycle_analysis": "requirements",
    "scenario_exploration": "requirements",
    "use_case_analysis": "requirements",
    "operational_scenario": "requirements",
    "activity_analysis": "requirements",
    "system_requirement_derivation": "requirements",
    "function_identification": "functional",
    "functional_decomposition": "functional",
    "functional_interaction": "functional",
    "functional_scenario": "functional",
    "functional_requirement": "functional",
    "logical_analysis": "logical",
    "interface_sequence_state": "logical",
    "dependency_clustering": "logical",
    "architecture_evaluation": "logical",
    "physical_candidates": "physical",
    "allocation_tradeoff": "physical",
    "technical_requirement": "physical",
    "constraint_propagation": "physical",
    "feasibility_selection": "physical",
    "fmea_stpa_hazard": "assurance",
    "verification_validation": "assurance",
    "reverse_feasibility": "assurance",
    "global_cross_analysis": "assurance",
}
_TASK_PRIORITY = {
    "system_requirement_derivation": 0,
    "function_identification": 1,
    "functional_decomposition": 2,
    "logical_analysis": 3,
    "dependency_clustering": 4,
    "architecture_evaluation": 5,
    "physical_candidates": 6,
    "allocation_tradeoff": 7,
    "constraint_propagation": 8,
    "feasibility_selection": 9,
    "fmea_stpa_hazard": 10,
    "verification_validation": 11,
    "global_cross_analysis": 12,
}


@dataclass(frozen=True, slots=True)
class ControllerAction:
    """One user-visible next action selected from engineering feedback."""

    id: str
    kind: str
    task_id: str
    stage: str
    priority: str
    entity_ids: tuple[str, ...] = ()
    reason: str = ""
    options: tuple[Mapping[str, object], ...] = ()

    def as_dict(self) -> Mapping[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "task_id": self.task_id,
            "stage": self.stage,
            "priority": self.priority,
            "entity_ids": list(self.entity_ids),
            "reason": self.reason,
            "options": [dict(option) for option in self.options],
        }


@dataclass(frozen=True, slots=True)
class ControllerPlan:
    """Bounded control plan; it does not mutate the graph by itself."""

    status: str
    objective: str
    findings: tuple[str, ...] = ()
    actions: tuple[ControllerAction, ...] = ()
    impacted_entity_ids: tuple[str, ...] = ()
    impacted_stages: tuple[str, ...] = ()

    @property
    def next_action(self) -> ControllerAction | None:
        return self.actions[0] if self.actions else None

    def as_dict(self) -> Mapping[str, object]:
        return {
            "status": self.status,
            "objective": self.objective,
            "findings": list(self.findings),
            "actions": [action.as_dict() for action in self.actions],
            "next_action": self.next_action.as_dict() if self.next_action else None,
            "impacted_entity_ids": list(self.impacted_entity_ids),
            "impacted_stages": list(self.impacted_stages),
        }


class SystemsEngineeringController:
    """Turn deterministic findings into bounded, explainable next actions."""

    def __init__(self, methodology_engine: MethodologyEngine | None = None):
        self.methodology_engine = methodology_engine or MethodologyEngine()

    def plan(
        self,
        graph: ModelGraph,
        report: MethodologyReport | None = None,
        *,
        max_actions: int = 8,
    ) -> ControllerPlan:
        analysis = report or self.methodology_engine.analyze(graph)
        actions: list[ControllerAction] = []
        seen: set[tuple[str, str, tuple[str, ...]]] = set()
        for finding in analysis.findings:
            action = self._action_for(finding, analysis)
            if action is None:
                continue
            key = (action.kind, action.task_id, action.entity_ids)
            if key in seen:
                continue
            seen.add(key)
            actions.append(action)
        actions.sort(key=lambda item: (
            0 if item.priority == "P0" else 1,
            _TASK_PRIORITY.get(item.task_id, len(_TASK_PRIORITY)),
            item.id,
        ))
        bounded = tuple(actions[: max(1, int(max_actions))])
        return ControllerPlan(
            "needs_action" if bounded else "complete",
            "把当前 ModelGraph 推进到可追溯、可验证、可复核的系统工程模型",
            tuple(dict.fromkeys(item.code for item in analysis.findings)),
            bounded,
            analysis.impacted_entity_ids,
            analysis.impacted_stages,
        )

    def _action_for(
        self,
        finding: MethodologyFinding,
        report: MethodologyReport,
    ) -> ControllerAction | None:
        task_id = self._task_for(finding)
        if not task_id:
            return None
        action_kind = "reanalyze" if finding.entity_ids else "collect_input"
        options: tuple[Mapping[str, object], ...] = ()
        if finding.code in {"physical_constraint_conflict", "logical_partition_needs_review"}:
            action_kind = "trade_study"
            options = self._trade_options(finding, report)
        elif finding.code in {"verification_execution_failed", "validation_execution_failed"}:
            action_kind = "trade_study" if finding.severity == "error" else "collect_evidence"
            options = self._trade_options(finding, report) if action_kind == "trade_study" else ()
        elif finding.code in {
            "physical_measurement_required",
            "verification_evidence_missing",
            "validation_evidence_missing",
        }:
            action_kind = "collect_evidence"
        priority = "P0" if finding.severity == "error" else "P1"
        identity = (action_kind, task_id, finding.entity_ids, finding.code)
        return ControllerAction(
            f"controller-action-{canonical_hash(identity)[:16]}",
            action_kind,
            task_id,
            _TASK_TO_STAGE.get(task_id, finding.stage),
            priority,
            tuple(finding.entity_ids),
            finding.message,
            options,
        )

    @staticmethod
    def _task_for(finding: MethodologyFinding) -> str:
        for item in finding.recommended_actions:
            task_id = str(item)
            if task_id in _TASK_TO_STAGE:
                return task_id
        return ""

    @staticmethod
    def _trade_options(
        finding: MethodologyFinding,
        report: MethodologyReport,
    ) -> tuple[Mapping[str, object], ...]:
        metric_name = (
            "physical_resolution_options"
            if finding.code == "physical_constraint_conflict"
            else "vv_execution_resolution_options"
            if finding.code in {"verification_execution_failed", "validation_execution_failed"}
            else "logical_trade_study"
        )
        raw_options = report.metrics.get(metric_name, ())
        if not isinstance(raw_options, Sequence) or isinstance(raw_options, (str, bytes)):
            return ()
        options = []
        for raw in raw_options:
            if not isinstance(raw, Mapping):
                continue
            option = str(raw.get("option", raw.get("alternative", ""))).strip()
            task = str(raw.get("task", "architecture_evaluation")).strip()
            if not option or not task:
                continue
            options.append({
                "id": f"trade-option-{canonical_hash((finding.code, option, task))[:12]}",
                "option": option,
                "task_id": task,
                "stage": _TASK_TO_STAGE.get(task, finding.stage),
                "impact": str(raw.get("impact", raw.get("rationale", ""))),
                "requires_user_decision": True,
            })
        return tuple(options)
