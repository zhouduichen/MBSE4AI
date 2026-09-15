"""Deterministic systems-engineering analysis over the semantic ModelGraph."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from rflp_lite.domain.entities import Entity, EntityKind, EntityStatus
from rflp_lite.domain.model import ModelGraph
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.completion import CompletionResult, evaluate_vertical_stage
from rflp_lite.methodology.architecture_synthesis import (
    ArchitectureSynthesis,
    is_unknown_measurement,
    synthesize_architecture,
)
from rflp_lite.methodology.impact import TASK_ORDER, TypedImpactPlanner
from rflp_lite.methodology.trace_rules import (
    is_technical_requirement,
    rflp_paths,
    requirement_trace_scope,
    vv_scope_matches,
)
from rflp_lite.methodology.vv_contract import VV_PLAN_FIELDS, missing_vv_plan_fields
from rflp_lite.methodology.vertical_generation import stage_spec


_INACTIVE = frozenset({EntityStatus.REJECTED, EntityStatus.DEPRECATED})
_READY = frozenset({EntityStatus.VALIDATED, EntityStatus.ACCEPTED, EntityStatus.LOCKED})
_PHYSICAL_FIELDS = (
    "mass_kg", "power_w", "compute", "memory_mb", "latency_ms",
    "bandwidth_mbps", "cost", "thermal", "reliability", "availability", "endurance_h",
)
_OPERATIONAL_KINDS = (
    EntityKind.SYSTEM, EntityKind.STAKEHOLDER, EntityKind.CONCERN,
    EntityKind.LIFECYCLE_STAGE, EntityKind.LIFECYCLE_TRANSITION,
    EntityKind.SCENARIO_HYPOTHESIS, EntityKind.USE_CASE,
    EntityKind.OPERATIONAL_SCENARIO, EntityKind.ACTIVITY, EntityKind.REQUIREMENT,
)
_TASK_ORDER = TASK_ORDER
_VERTICAL_COMPLETION_STAGE_BY_TASK = {
    "vertical.requirements": "requirements",
    "vertical.functional": "functional",
    "vertical.logical": "logical",
    "vertical.physical": "physical",
    "vertical.verification_validation": "verification_validation",
}


@dataclass(frozen=True, slots=True)
class MethodologyFinding:
    code: str
    severity: str
    stage: str
    entity_ids: tuple[str, ...] = ()
    message: str = ""
    recommended_actions: tuple[str, ...] = ()
    impact_paths: tuple[tuple[str, ...], ...] = ()

    def as_dict(self) -> Mapping[str, object]:
        return {
            "code": self.code,
            "severity": self.severity,
            "stage": self.stage,
            "entity_ids": list(self.entity_ids),
            "message": self.message,
            "recommended_actions": list(self.recommended_actions),
            "impact_paths": [list(path) for path in self.impact_paths],
        }


@dataclass(frozen=True, slots=True)
class MethodologyReport:
    findings: tuple[MethodologyFinding, ...] = ()
    metrics: Mapping[str, object] = field(default_factory=dict)
    decisions: tuple[Mapping[str, object], ...] = ()
    impacted_entity_ids: tuple[str, ...] = ()
    impacted_stages: tuple[str, ...] = ()
    recommended_tasks: tuple[str, ...] = ()
    impact_paths: tuple[tuple[str, ...], ...] = ()

    def as_dict(self) -> Mapping[str, object]:
        return {
            "findings": [item.as_dict() for item in self.findings],
            "metrics": dict(self.metrics),
            "decisions": [dict(item) for item in self.decisions],
            "impacted_entity_ids": list(self.impacted_entity_ids),
            "impacted_stages": list(self.impacted_stages),
            "recommended_tasks": list(self.recommended_tasks),
            "impact_paths": [list(path) for path in self.impact_paths],
        }


@dataclass(frozen=True, slots=True)
class _VvAnalysisStats:
    verification_count: int
    validation_count: int
    structured_verification: int
    structured_validation: int
    verification_evidence: int
    validation_evidence: int
    vv_scope_cases: int
    vv_scope_matches: int
    covered_branches: frozenset[str]


_GUIDANCE_STAGE_BY_TASK = {
    "vertical.requirements": "requirements",
    "vertical.functional": "functional",
    "vertical.logical": "logical",
    "vertical.physical": "physical",
    "vertical.verification_validation": "assurance",
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
_GUIDANCE_METRICS = {
    "requirements": (
        "operational_context_coverage", "operational_requirement_count",
    ),
    "functional": (
        "functional_requirement_coverage", "functional_flow_coverage",
        "functional_scenario_coverage", "functional_decomposition_coverage",
    ),
    "logical": (
        "logical_allocation_coverage", "logical_state_model_coverage",
        "logical_partition_quality", "logical_cross_component_exchange_count",
        "logical_timing_constraint_count", "logical_timing_cut_count",
        "logical_safety_isolation_count", "logical_safety_violation_count",
        "logical_safety_review_required",
    ),
    "physical": (
        "physical_allocation_coverage", "physical_feasibility",
        "physical_conflict_count", "physical_candidate_conflict_count",
        "physical_budget_conflict_count", "physical_unknown_field_count",
    ),
    "assurance": (
        "hazard_requirement_coverage", "failure_mode_requirement_coverage",
        "structured_verification_coverage", "structured_validation_coverage",
        "verification_evidence_coverage", "validation_evidence_coverage",
    ),
}


def build_methodology_guidance(
    report: MethodologyReport,
    task_id: str,
    *,
    stage_completion: CompletionResult | None = None,
) -> Mapping[str, object]:
    """Expose bounded deterministic guidance to the next generation task."""

    stage = _GUIDANCE_STAGE_BY_TASK.get(task_id, "")
    metrics = {
        key: report.metrics[key]
        for key in _GUIDANCE_METRICS.get(stage, ())
        if key in report.metrics
    }
    guidance = {
        "version": "methodology-guidance.v1",
        "task_id": task_id,
        "stage": stage,
        "metrics": metrics,
        "findings": [
            finding.as_dict()
            for finding in report.findings
            if not stage or finding.stage == stage
        ][:6],
        "recommended_tasks": list(report.recommended_tasks[:8]),
        "decisions": [dict(item) for item in report.decisions[-4:]],
        "impacted_entity_ids": list(report.impacted_entity_ids[:24]),
    }
    if task_id.startswith("vertical."):
        guidance["stage_contract"] = stage_spec(
            task_id.removeprefix("vertical.")
        ).as_contract()
    synthesis = report.metrics.get("architecture_synthesis")
    if isinstance(synthesis, Mapping) and stage in {"logical", "physical"}:
        section = synthesis.get(stage)
        if isinstance(section, Mapping):
            guidance["architecture_synthesis"] = {
                stage: _bounded_architecture_guidance(section, stage),
            }
    if stage_completion is not None:
        guidance["stage_completion"] = {
            "checks": [dict(check) for check in stage_completion.checks],
            "issue_codes": list(stage_completion.issue_codes),
        }
        coverage = next(
            (
                check for check in stage_completion.checks
                if str(check.get("id", "")).startswith("requirement_coverage:")
            ),
            None,
        )
        if coverage is not None:
            guidance["requirement_coverage"] = dict(coverage)
    return guidance


def _bounded_architecture_guidance(
    section: Mapping[str, object],
    stage: str,
) -> Mapping[str, object]:
    """Keep candidate evidence useful without consuming the task context."""

    bounded = dict(section)
    item_key = "candidates" if stage == "logical" else "rows"
    items = section.get(item_key)
    if isinstance(items, (list, tuple)):
        bounded[item_key] = list(items[:8])
        bounded[f"{item_key}_truncated"] = len(items) > 8
    if stage == "physical":
        budgets = section.get("budget_analyses")
        if isinstance(budgets, (list, tuple)):
            bounded["budget_analyses"] = list(budgets[:8])
            bounded["budget_analyses_truncated"] = len(budgets) > 8
    return bounded


class MethodologyEngine:
    """Analyze graph quality without mutating the graph or calling an LLM."""

    def analyze(
        self,
        graph: ModelGraph,
        *,
        changed_entity_ids: Sequence[str] = (),
    ) -> MethodologyReport:
        index = graph.entity_index
        findings: list[MethodologyFinding] = []
        decisions: list[Mapping[str, object]] = []
        metrics = {}
        architecture = synthesize_architecture(graph)
        self._analyze_operational(graph, index, findings, decisions, metrics)
        self._analyze_functional(graph, index, findings, decisions, metrics)
        self._analyze_logical(graph, index, findings, decisions, metrics, architecture)
        self._analyze_physical(graph, index, findings, decisions, metrics, architecture)
        self._analyze_vv(graph, index, findings, decisions, metrics)
        names = {item.id: item.meta.name for item in graph.entities}
        metrics["architecture_synthesis"] = architecture.as_dict(names)
        impact = self._impact(graph, index, changed_entity_ids)
        finding_tasks = {
            task for finding in findings for task in finding.recommended_actions
        }
        recommended_tasks = impact[2] or tuple(
            task for task in _TASK_ORDER if task in finding_tasks
        )
        findings.sort(key=lambda item: (item.stage, item.code, item.entity_ids))
        decisions.sort(key=lambda item: (str(item.get("step", "")), str(item.get("decision", ""))))
        return MethodologyReport(
            tuple(findings),
            metrics,
            tuple(decisions),
            impact[0],
            impact[1],
            recommended_tasks,
            impact[3],
        )

    def context_guidance(self, graph: ModelGraph, task_id: str) -> Mapping[str, object]:
        """Return the current report in a bounded form suitable for an LLM."""

        stage = _VERTICAL_COMPLETION_STAGE_BY_TASK.get(task_id)
        completion = evaluate_vertical_stage(stage, graph) if stage else None
        return build_methodology_guidance(
            self.analyze(graph),
            task_id,
            stage_completion=completion,
        )

    def _analyze_operational(self, graph, index, findings, decisions, metrics) -> None:
        present = {
            kind: _active(index, kind)
            for kind in _OPERATIONAL_KINDS
        }
        present[EntityKind.REQUIREMENT] = tuple(
            item for item in present[EntityKind.REQUIREMENT]
            if not is_technical_requirement(item)
        )
        present_count = sum(bool(items) for items in present.values())
        metrics["operational_context_coverage"] = _ratio(present_count, len(_OPERATIONAL_KINDS))
        actions = {
            EntityKind.SYSTEM: ("system_definition",),
            EntityKind.STAKEHOLDER: ("stakeholder_analysis",),
            EntityKind.CONCERN: ("stakeholder_analysis",),
            EntityKind.LIFECYCLE_STAGE: ("lifecycle_analysis",),
            EntityKind.LIFECYCLE_TRANSITION: ("lifecycle_analysis",),
            EntityKind.SCENARIO_HYPOTHESIS: ("scenario_exploration",),
            EntityKind.USE_CASE: ("use_case_analysis",),
            EntityKind.OPERATIONAL_SCENARIO: ("operational_scenario",),
            EntityKind.ACTIVITY: ("activity_analysis",),
            EntityKind.REQUIREMENT: ("system_requirement_derivation",),
        }
        for kind, items in present.items():
            metrics[f"operational_{kind.value}_count"] = len(items)
            if not items:
                findings.append(MethodologyFinding(
                    f"operational_{kind.value}_missing", "warning", "requirements", (),
                    f"Operational Analysis 缺少 {kind.value} 实体。",
                    actions[kind],
                ))
        relations = _relation_targets(graph, index, RelationPredicate.PARTICIPATES_IN)
        if present[EntityKind.STAKEHOLDER] and present[EntityKind.OPERATIONAL_SCENARIO]:
            if not any(
                target.kind is EntityKind.OPERATIONAL_SCENARIO
                for stakeholder in present[EntityKind.STAKEHOLDER]
                for target_id in relations.get(stakeholder.id, ())
                for target in (index[target_id],)
            ):
                findings.append(MethodologyFinding(
                    "operational_scenario_without_actor", "warning", "requirements",
                    tuple(item.id for item in present[EntityKind.OPERATIONAL_SCENARIO]),
                    "Operational Scenario 没有明确的 Stakeholder 参与关系。",
                    ("stakeholder_analysis", "operational_scenario"),
                ))
        activity_lifecycles = _relation_targets(graph, index, RelationPredicate.OCCURS_IN)
        for activity in present[EntityKind.ACTIVITY]:
            if not any(
                index[target_id].kind is EntityKind.LIFECYCLE_STAGE
                for target_id in activity_lifecycles.get(activity.id, ())
            ):
                findings.append(MethodologyFinding(
                    "activity_without_lifecycle", "warning", "requirements", (activity.id,),
                    f"Activity“{activity.meta.name}”没有生命周期归属。",
                    ("lifecycle_analysis", "activity_analysis"),
                ))
        decisions.extend((
            {
                "step": "operational_context_check",
                "decision": "检查系统、利益相关者、生命周期、场景、用例、活动和需求是否形成上下文",
                "basis": [item.id for items in present.values() for item in items],
            },
            {
                "step": "system_requirement_derivation",
                "decision": "保留从运行活动推导系统需求的可追踪入口",
                "basis": [item.id for item in present[EntityKind.REQUIREMENT]],
            },
        ))

    def _analyze_functional(self, graph, index, findings, decisions, metrics) -> None:
        requirements = tuple(
            item for item in _active(index, EntityKind.REQUIREMENT)
            if not is_technical_requirement(item)
        )
        functions = _ready(index, EntityKind.FUNCTION)
        flows = _ready(index, EntityKind.FUNCTIONAL_FLOW)
        scenarios = _ready(index, EntityKind.FUNCTIONAL_SCENARIO)
        satisfied = _relation_targets(
            graph, index, RelationPredicate.SATISFIED_BY, target_ready_only=True
        )
        requirement_functions = {
            requirement.id: tuple(
                target for target in satisfied.get(requirement.id, ())
                if index[target].kind is EntityKind.FUNCTION
            )
            for requirement in requirements
        }
        function_flows = _relation_targets(
            graph, index, RelationPredicate.EXCHANGES_WITH, target_ready_only=True
        )
        function_scenarios = _relation_targets(
            graph, index, RelationPredicate.DERIVED_FROM, target_ready_only=True
        )
        covered_requirements = sum(bool(targets) for targets in requirement_functions.values())
        covered_functions = sum(bool(
            [target for target in function_flows.get(function.id, ()) if index[target].kind is EntityKind.FUNCTIONAL_FLOW]
        ) for function in functions)
        scenario_functions = sum(bool(
            [target for target in function_scenarios.get(function.id, ()) if index[target].kind is EntityKind.FUNCTIONAL_SCENARIO]
        ) for function in functions)
        decomposed_functions = sum(
            bool(function.payload.get("decomposition"))
            for function in functions
        )
        metrics["functional_requirement_coverage"] = _ratio(covered_requirements, len(requirements))
        metrics["functional_flow_coverage"] = _ratio(covered_functions, len(functions))
        metrics["functional_scenario_coverage"] = _ratio(scenario_functions, len(functions))
        metrics["functional_decomposition_coverage"] = _ratio(
            decomposed_functions, len(functions)
        )
        metrics["functional_function_count"] = len(functions)
        metrics["functional_flow_count"] = len(flows)
        metrics["functional_scenario_count"] = len(scenarios)
        for requirement, targets in requirement_functions.items():
            if not targets:
                findings.append(MethodologyFinding(
                    "functional_requirement_uncovered", "warning", "functional", (requirement,),
                    "系统需求没有对应的 Function 覆盖。",
                    ("function_identification", "functional_decomposition"),
                ))
        for function in functions:
            if not function.payload.get("decomposition"):
                findings.append(MethodologyFinding(
                    "functional_decomposition_missing", "warning", "functional", (function.id,),
                    f"功能“{function.meta.name}”没有显式功能分解步骤。",
                    ("functional_decomposition",),
                ))
            if not any(index[target].kind is EntityKind.FUNCTIONAL_FLOW for target in function_flows.get(function.id, ())):
                findings.append(MethodologyFinding(
                    "functional_flow_missing", "warning", "functional", (function.id,),
                    f"功能“{function.meta.name}”没有功能流交互。",
                    ("functional_interaction",),
                ))
        decisions.extend((
            {
                "step": "function_identification",
                "decision": "检查每条系统需求是否映射到系统行为",
                "basis": [item.id for item in requirements],
            },
            {
                "step": "functional_interaction",
                "decision": "检查功能之间是否通过功能流表达交互",
                "basis": [item.id for item in flows],
            },
        ))

    def _analyze_logical(
        self,
        graph,
        index,
        findings,
        decisions,
        metrics,
        architecture: ArchitectureSynthesis,
    ) -> None:
        functions = _ready(index, EntityKind.FUNCTION)
        components = _ready(index, EntityKind.LOGICAL_COMPONENT)
        allocations = _relation_targets(
            graph, index, RelationPredicate.ALLOCATED_TO, target_ready_only=True
        )
        function_to_components = {
            entity.id: tuple(
                target for target in allocations.get(entity.id, ())
                if index[target].kind is EntityKind.LOGICAL_COMPONENT
            )
            for entity in functions
        }
        assigned = {item.id for item in functions if function_to_components[item.id]}
        metrics["logical_function_count"] = len(functions)
        metrics["logical_component_count"] = len(components)
        states = _ready(index, EntityKind.STATE)
        metrics["logical_state_count"] = len(states)
        metrics["logical_state_model_coverage"] = 1.0 if states else 0.0
        metrics["logical_allocation_coverage"] = _ratio(len(assigned), len(functions))
        metrics["logical_partition_count"] = len(components)
        if functions and not components:
            findings.append(MethodologyFinding(
                "logical_architecture_missing", "error", "logical",
                tuple(item.id for item in functions),
                "存在系统功能但没有逻辑架构组件。",
                ("logical_analysis", "dependency_clustering"),
            ))
        for function in functions:
            if not function_to_components[function.id]:
                findings.append(MethodologyFinding(
                    "logical_function_unallocated", "warning", "logical", (function.id,),
                    f"功能“{function.meta.name}”没有分配到逻辑组件。",
                    ("logical_analysis", "dependency_clustering"),
                ))
        if components and not states:
            findings.append(MethodologyFinding(
                "logical_state_model_missing", "warning", "logical",
                tuple(item.id for item in components),
                "逻辑架构没有显式 State 模型，无法表达关键状态转换和异常分支。",
                ("interface_sequence_state", "logical_analysis"),
            ))
        component_functions = {
            component.id: tuple(
                function.id for function in functions
                if component.id in function_to_components[function.id]
            )
            for component in components
        }
        for component in components:
            function_ids = component_functions[component.id]
            if not function_ids:
                findings.append(MethodologyFinding(
                    "logical_component_orphan", "warning", "logical", (component.id,),
                    f"逻辑组件“{component.meta.name}”没有承载功能。",
                    ("dependency_clustering", "architecture_evaluation"),
                ))
            decisions.extend(_logical_decisions(component, function_ids))
        crossings = _count_interface_crossings(graph, index, function_to_components)
        metrics["logical_cross_component_exchange_count"] = crossings
        current_candidate = next(
            (
                item for item in architecture.logical_candidates
                if item.alternative == "current_dependency_partition"
            ),
            None,
        )
        representative = current_candidate or (
            architecture.logical_candidates[0]
            if architecture.logical_candidates else None
        )
        safety_review = bool(
            representative and representative.safety_violation_count
        )
        partition_quality = _partition_quality(components)
        if crossings and len(components) > 1 and partition_quality == "reviewed":
            partition_quality = "needs_review"
        if safety_review:
            partition_quality = "needs_review"
        metrics["logical_partition_quality"] = partition_quality
        if components and metrics["logical_partition_quality"] == "needs_review":
            findings.append(MethodologyFinding(
                "logical_partition_needs_review", "warning", "logical",
                tuple(item.id for item in components),
                _logical_partition_review_message(crossings, safety_review),
                ("dependency_clustering", "architecture_evaluation"),
            ))
        metrics["logical_partition_candidates"] = [
            {
                "component_id": component.id,
                "function_ids": list(component_functions[component.id]),
                "basis": str(component.payload.get("partition_basis", "")),
                "cohesion": component.payload.get("cohesion", "unknown"),
                "coupling": component.payload.get("coupling", "unknown"),
            }
            for component in components
        ]
        names = {item.id: item.meta.name for item in functions}
        candidates = [
            item.as_dict(names) for item in architecture.logical_candidates
        ]
        metrics["logical_trade_study"] = candidates
        metrics["logical_architecture_recommended"] = (
            candidates[0]["alternative"] if candidates else ""
        )
        metrics["logical_timing_constraint_count"] = (
            representative.timing_constraint_count if representative else 0
        )
        metrics["logical_timing_cut_count"] = (
            representative.timing_cut_count if representative else 0
        )
        metrics["logical_safety_isolation_count"] = (
            representative.safety_isolation_count if representative else 0
        )
        metrics["logical_safety_violation_count"] = (
            representative.safety_violation_count if representative else 0
        )
        metrics["logical_safety_review_required"] = bool(
            safety_review
        )
        if candidates:
            decisions.append({
                "step": "logical_architecture_trade_study",
                "decision": (
                    f"推荐 {candidates[0]['alternative']}，评分 "
                    f"{candidates[0]['score']} / 100"
                ),
                "basis": [item.id for item in functions],
                "alternatives": candidates,
            })

    def _analyze_physical(
        self,
        graph,
        index,
        findings,
        decisions,
        metrics,
        architecture: ArchitectureSynthesis,
    ) -> None:
        physicals, allocations = _physical_scope(
            graph, index, findings, metrics,
        )
        requirements_by_physical = _requirements_by_physical(graph, index, allocations)
        unknown_fields, candidate_conflicts = _physical_candidate_evidence(
            physicals, requirements_by_physical,
        )
        _append_candidate_conflict_findings(findings, candidate_conflicts)
        budget_conflicts = _append_budget_conflict_findings(
            graph, findings, architecture.system_budgets,
        )
        if unknown_fields:
            findings.append(MethodologyFinding(
                "physical_measurement_required", "warning", "physical",
                tuple(item.id for item in physicals),
                f"物理候选仍有 {unknown_fields} 个 SWaP-C/工程字段需要测量或证据。",
                ("physical_candidates", "feasibility_selection"),
            ))
        _record_physical_feasibility_metrics(
            metrics, physicals, unknown_fields, candidate_conflicts,
            budget_conflicts, architecture.system_budgets,
        )
        feasibility_rows = {
            row.physical_id: row.as_dict()
            for row in architecture.physical_rows
        }
        metrics["physical_feasibility_matrix"] = [
            feasibility_rows[item.id]
            for item in physicals
            if item.id in feasibility_rows
        ]
        _record_physical_trade_study(
            metrics, decisions, physicals, feasibility_rows,
            architecture.system_budgets,
        )

    def _analyze_vv(self, graph, index, findings, decisions, metrics) -> None:
        requirements = _active(index, EntityKind.REQUIREMENT)
        hazards = _ready(index, EntityKind.HAZARD)
        failure_modes = _ready(index, EntityKind.FAILURE_MODE)
        verifications = _relation_targets(
            graph, index, RelationPredicate.VERIFIED_BY, target_ready_only=True
        )
        validations = _relation_targets(
            graph, index, RelationPredicate.VALIDATED_BY, target_ready_only=True
        )
        derived_from = _relation_targets(graph, index, RelationPredicate.DERIVED_FROM)
        mitigations = _relation_targets(
            graph, index, RelationPredicate.MITIGATED_BY, target_ready_only=True
        )
        activities = _ready(index, EntityKind.ACTIVITY)
        branch_names = tuple(
            branch
            for activity in activities
            for branch in _branches(activity)
        )
        self._record_vv_risk_coverage(
            requirements, hazards, failure_modes, index, derived_from, mitigations,
            findings, metrics,
        )
        vv_cases, executed_cases, failed_cases, execution_metrics = _vv_execution_summary(index)
        metrics.update(execution_metrics)
        metrics["vv_execution_resolution_options"] = self._vv_resolution_options(failed_cases)
        stats = self._analyze_vv_cases(
            graph, index, requirements, verifications, validations, findings,
        )
        _record_vv_case_metrics(metrics, stats, requirements, branch_names)
        if branch_names and set(branch_names) - stats.covered_branches:
            findings.append(MethodologyFinding(
                "activity_branch_uncovered", "warning", "assurance",
                tuple(item.id for item in activities),
                "Activity 的决策、失败或边界分支没有映射到 V&V 场景。",
                ("verification_validation", "global_cross_analysis"),
            ))
        metrics["end_to_end_vv_coverage"] = _ratio(
            sum(bool(verifications.get(item.id)) and bool(validations.get(item.id)) for item in requirements),
            len(requirements),
        )
        _record_vv_decisions(
            decisions, requirements, verifications, validations,
            vv_cases, executed_cases, failed_cases,
        )

    def _record_vv_risk_coverage(
        self, requirements, hazards, failure_modes, index, derived_from,
        mitigations, findings, metrics,
    ) -> None:
        hazard_ids = _requirement_ids_for_risks(hazards, requirements, index, derived_from)
        failure_ids = _requirement_ids_for_risks(failure_modes, requirements, index, derived_from)
        risk_ids = hazard_ids | failure_ids
        metrics.update({
            "hazard_count": len(hazards),
            "failure_mode_count": len(failure_modes),
            "hazard_requirement_coverage": _ratio(len(hazard_ids), len(requirements)),
            "failure_mode_requirement_coverage": _ratio(len(failure_ids), len(requirements)),
            "hazard_failure_mode_coverage": _ratio(len(risk_ids), len(requirements)),
        })
        for requirement in requirements:
            if requirement.id not in hazard_ids:
                findings.append(MethodologyFinding(
                    "hazard_analysis_missing", "warning", "assurance", (requirement.id,),
                    f"需求“{requirement.meta.name}”没有关联 Hazard 分析。", ("fmea_stpa_hazard",),
                ))
            if requirement.id not in failure_ids:
                findings.append(MethodologyFinding(
                    "failure_mode_missing", "warning", "assurance", (requirement.id,),
                    f"需求“{requirement.meta.name}”没有关联 FailureMode 分析。",
                    ("fmea_stpa_hazard", "reverse_feasibility"),
                ))
        self._vv_risk_findings(hazards, failure_modes, index, mitigations, findings)

    def _analyze_vv_cases(
        self, graph, index, requirements, verifications, validations, findings,
    ) -> _VvAnalysisStats:
        values = [0, 0, 0, 0, 0, 0, 0, 0]
        covered_branches: set[str] = set()
        for requirement in requirements:
            verification_cases = _typed_vv_cases(index, verifications.get(requirement.id, ()), EntityKind.VERIFICATION_CASE)
            validation_cases = _typed_vv_cases(index, validations.get(requirement.id, ()), EntityKind.VALIDATION_CASE)
            verification_stats = self._vv_case_group(requirement, verification_cases, "verification", findings)
            validation_stats = self._vv_case_group(requirement, validation_cases, "validation", findings)
            values[0] += bool(verification_cases)
            values[1] += bool(validation_cases)
            values[2] += verification_stats[0]
            values[3] += validation_stats[0]
            values[4] += verification_stats[1]
            values[5] += validation_stats[1]
            covered_branches.update(verification_stats[2] | validation_stats[2])
            for case in (*verification_cases, *validation_cases):
                values[6] += 1
                scope_matches = vv_scope_matches(graph, requirement.id, case)
                values[7] += scope_matches
                if not scope_matches:
                    _append_vv_scope_finding(graph, requirement, case, findings)
                self._vv_execution_findings(case, requirements, verifications, validations, graph, findings)
        return _VvAnalysisStats(*values, frozenset(covered_branches))

    def _vv_case_group(self, requirement, cases, case_type, findings):
        if not cases:
            code = f"{case_type}_missing"
            label = "VerificationCase" if case_type == "verification" else "ValidationCase"
            findings.append(MethodologyFinding(
                code, "warning", "assurance", (requirement.id,),
                f"需求“{requirement.meta.name}”没有 {label}。", ("verification_validation",),
            ))
            return 0, 0, frozenset()
        self._vv_findings(case_type, cases, findings)
        return (
            any(_complete_vv_case(item) for item in cases),
            any(_has_evidence(item) for item in cases),
            frozenset(_case_branches(cases)),
        )

    @staticmethod
    def _vv_resolution_options(failed_cases):
        if not any(item.payload.get("execution_status") == "failed" for item in failed_cases):
            return []
        return [
            {
                "option": "重构受影响功能",
                "task": "function_identification",
                "impact": "从失败的验证结果回到功能分解并重新检查下游链路",
            },
            {
                "option": "更换物理候选或计算架构",
                "task": "allocation_tradeoff",
                "impact": "保留需求，重新选择受影响的逻辑/物理实现",
            },
            {
                "option": "调整需求或资源预算",
                "task": "system_requirement_derivation",
                "impact": "需要利益相关者确认需求、预算或验收条件变化",
            },
            {
                "option": "修订验证条件并重新执行",
                "task": "verification_validation",
                "impact": "修订测试条件、程序或通过准则后重新执行",
            },
        ]

    @staticmethod
    def _vv_findings(label, cases, findings) -> None:
        for case in cases:
            missing = missing_vv_plan_fields(case.payload)
            if missing:
                findings.append(MethodologyFinding(
                    f"{label}_case_incomplete", "warning", "assurance", (case.id,),
                    f"{label.title()}Case“{case.meta.name}”缺少结构化字段：{', '.join(missing)}。",
                    ("verification_validation", "global_cross_analysis"),
                ))
            if not _has_evidence(case):
                findings.append(MethodologyFinding(
                    f"{label}_evidence_missing", "warning", "assurance", (case.id,),
                    f"{label.title()}Case“{case.meta.name}”尚未关联执行证据。",
                    ("verification_validation", "global_cross_analysis"),
                ))

    @staticmethod
    def _vv_risk_findings(hazards, failure_modes, index, mitigations, findings) -> None:
        for risk in (*hazards, *failure_modes):
            covered = any(
                index[target_id].kind in {
                    EntityKind.REQUIREMENT,
                    EntityKind.FUNCTION,
                    EntityKind.VERIFICATION_CASE,
                }
                for target_id in mitigations.get(risk.id, ())
            )
            if not covered:
                findings.append(MethodologyFinding(
                    "risk_without_mitigation", "warning", "assurance", (risk.id,),
                    f"风险对象“{risk.meta.name}”没有关联需求、功能或 VerificationCase 缓解措施。",
                    ("fmea_stpa_hazard", "verification_validation"),
                ))

    @staticmethod
    def _vv_execution_findings(
        case,
        requirements,
        verifications,
        validations,
        graph,
        findings,
    ) -> None:
        outcome = str(case.payload.get("execution_status", "")).strip()
        if outcome not in {"failed", "blocked", "inconclusive"}:
            return
        requirement_ids = {
            str(item) for item in case.payload.get("requirement_ids", ())
            if str(item)
        }
        requirement_ids.update(
            requirement.id
            for requirement in requirements
            if case.id in verifications.get(requirement.id, ())
            or case.id in validations.get(requirement.id, ())
        )
        label = "Verification" if case.kind is EntityKind.VERIFICATION_CASE else "Validation"
        actions = (
            ("function_identification", "logical_analysis", "physical_candidates", "verification_validation")
            if outcome == "failed"
            else ("verification_validation", "global_cross_analysis")
        )
        index = graph.entity_index
        impacted_ids, _stages, _tasks, impact_paths = MethodologyEngine._impact(
            graph,
            index,
            tuple(sorted(requirement_ids)),
        )
        entity_ids = tuple(dict.fromkeys((case.id, *sorted(requirement_ids), *impacted_ids)))
        findings.append(MethodologyFinding(
            f"{label.casefold()}_execution_failed",
            "error" if outcome == "failed" else "warning",
            "assurance",
            entity_ids,
            f"{label}Case“{case.meta.name}”执行结果为 {outcome}，需要检查驱动需求及其下游架构。",
            actions,
            impact_paths[:24],
        ))

    @staticmethod
    def _impact(graph, index, changed_entity_ids):
        if not changed_entity_ids:
            return (), (), (), ()
        plan = TypedImpactPlanner().plan(graph, changed_entity_ids)
        return (
            plan.impacted_entity_ids,
            plan.impacted_stages,
            plan.recommended_tasks,
            tuple(path.entity_ids for path in plan.impact_paths),
        )


def _typed_vv_cases(index, case_ids, kind: EntityKind) -> tuple[Entity, ...]:
    return tuple(
        index[item]
        for item in case_ids
        if item in index and index[item].kind is kind and index[item].meta.status in _READY
    )


def _append_vv_scope_finding(graph, requirement, case, findings) -> None:
    scope = requirement_trace_scope(graph, requirement.id)
    impacted_ids = tuple(dict.fromkeys(
        (case.id, requirement.id, *scope.function_ids,
         *scope.logical_component_ids, *scope.physical_ids)
    ))
    findings.append(MethodologyFinding(
        "vv_scope_mismatch", "error", "assurance", impacted_ids[:24],
        f"{case.meta.name} 的 V&V 作用域与当前需求到物理实现链不一致。",
        ("verification_validation", "global_cross_analysis"),
    ))


def _record_vv_case_metrics(metrics, stats: _VvAnalysisStats, requirements, branch_names) -> None:
    metrics.update({
        "verification_coverage": _ratio(stats.verification_count, len(requirements)),
        "validation_coverage": _ratio(stats.validation_count, len(requirements)),
        "structured_verification_coverage": _ratio(stats.structured_verification, len(requirements)),
        "structured_validation_coverage": _ratio(stats.structured_validation, len(requirements)),
        "verification_evidence_coverage": _ratio(stats.verification_evidence, len(requirements)),
        "validation_evidence_coverage": _ratio(stats.validation_evidence, len(requirements)),
        "vv_scope_consistency": _ratio(stats.vv_scope_matches, stats.vv_scope_cases),
        "vv_scope_mismatch_count": stats.vv_scope_cases - stats.vv_scope_matches,
        "activity_branch_coverage": (
            _ratio(len(set(branch_names) & stats.covered_branches), len(set(branch_names)))
            if branch_names else 1.0
        ),
    })


def _record_vv_decisions(
    decisions, requirements, verifications, validations,
    vv_cases, executed_cases, failed_cases,
) -> None:
    decisions.extend((
        {
            "step": "verification_validation",
            "decision": "分别检查工程验证和用户场景确认的覆盖与结构化准则",
            "basis": [item.id for item in requirements],
        },
        {
            "step": "global_cross_analysis",
            "decision": "检查每条需求是否同时具备 Verification 与 Validation",
            "basis": [
                item.id for item in requirements
                if verifications.get(item.id) and validations.get(item.id)
            ],
        },
        {
            "step": "verification_execution_feedback",
            "decision": (
                f"已执行 {len(executed_cases)}/{len(vv_cases)} 个 V&V Case，"
                f"其中 {len(failed_cases)} 个需要沿影响链迭代"
            ),
            "basis": [item.id for item in executed_cases],
        },
    ))


def _vv_execution_summary(index):
    cases = (
        *_ready(index, EntityKind.VERIFICATION_CASE),
        *_ready(index, EntityKind.VALIDATION_CASE),
    )
    executed = tuple(
        item for item in cases
        if str(item.payload.get("execution_status", "")).strip()
    )
    failed = tuple(
        item for item in executed
        if item.payload.get("execution_status") in {"failed", "blocked", "inconclusive"}
    )
    return (
        cases,
        executed,
        failed,
        {
            "vv_execution_case_count": len(cases),
            "vv_execution_coverage": _ratio(len(executed), len(cases)),
            "vv_execution_pass_coverage": _ratio(
                sum(item.payload.get("execution_status") == "passed" for item in executed),
                len(cases),
            ),
            "vv_execution_failure_count": len(failed),
        },
    )


def _physical_scope(graph, index, findings, metrics):
    """Resolve active physical architecture and its completion coverage."""

    logicals = _active(index, EntityKind.LOGICAL_COMPONENT)
    physicals = _active(index, EntityKind.PHYSICAL_BLOCK)
    ready_logical_ids = {item.id for item in _ready(index, EntityKind.LOGICAL_COMPONENT)}
    ready_physical_ids = {item.id for item in _ready(index, EntityKind.PHYSICAL_BLOCK)}
    allocations = _relation_targets(graph, index, RelationPredicate.ALLOCATED_TO)
    logical_to_physical = {
        logical.id: tuple(
            target for target in allocations.get(logical.id, ())
            if index[target].kind is EntityKind.PHYSICAL_BLOCK
        )
        for logical in logicals
    }
    assigned = {
        logical.id for logical in logicals
        if logical.id in ready_logical_ids
        and any(target in ready_physical_ids for target in logical_to_physical[logical.id])
    }
    metrics.update({
        "physical_logical_count": len(logicals),
        "physical_block_count": len(physicals),
        "physical_allocation_coverage": _ratio(len(assigned), len(logicals)),
    })
    for logical in logicals:
        if logical_to_physical[logical.id]:
            continue
        findings.append(MethodologyFinding(
            "physical_logical_unallocated", "warning", "physical", (logical.id,),
            f"逻辑组件“{logical.meta.name}”没有物理实现候选。",
            ("physical_candidates", "allocation_tradeoff"),
        ))
    return physicals, allocations


def _physical_candidate_evidence(physicals, requirements_by_physical):
    unknown_fields = 0
    conflicts = []
    for physical in physicals:
        unknown_fields += sum(
            is_unknown_measurement(physical.payload.get(field))
            for field in _PHYSICAL_FIELDS
        )
        for requirement in requirements_by_physical.get(physical.id, ()):
            for field_name, operator, limit in _constraints(requirement):
                value = _number(physical.payload.get(field_name))
                if value is not None and _violates(value, operator, limit):
                    conflicts.append((requirement, physical, field_name, operator, limit, value))
    return unknown_fields, conflicts


def _append_candidate_conflict_findings(findings, conflicts):
    for requirement, physical, field_name, operator, limit, value in conflicts:
        findings.append(MethodologyFinding(
            "physical_constraint_conflict", "error", "physical",
            (requirement.id, physical.id),
            f"物理候选“{physical.meta.name}”的 {field_name}={value} 不满足 {operator}={limit} 约束。",
            ("constraint_propagation", "feasibility_selection", "allocation_tradeoff"),
        ))


def _append_budget_conflict_findings(graph, findings, budgets):
    conflicts = tuple(
        conflict
        for budget in budgets
        if len(budget.physical_ids) > 1
        for conflict in budget.conflicts
    )
    for budget in budgets:
        if not budget.conflicts or len(budget.physical_ids) <= 1:
            continue
        paths = rflp_paths(graph, budget.requirement_id) or tuple(
            (budget.requirement_id, physical_id)
            for physical_id in budget.physical_ids
        )
        fields = ", ".join(sorted({str(item.get("field", "")) for item in budget.conflicts}))
        findings.append(MethodologyFinding(
            "physical_budget_conflict", "error", "physical",
            (budget.requirement_id, *budget.physical_ids),
            f"系统资源预算需求“{budget.requirement_id}”在 {fields} 上超限，合计值违反约束。",
            ("constraint_propagation", "feasibility_selection", "allocation_tradeoff"),
            tuple(paths),
        ))
    return conflicts


def _record_physical_feasibility_metrics(
    metrics,
    physicals,
    unknown_fields,
    candidate_conflicts,
    budget_conflicts,
    budgets,
):
    metrics["physical_unknown_field_count"] = unknown_fields
    metrics["physical_candidate_conflict_count"] = len(candidate_conflicts)
    metrics["physical_budget_conflict_count"] = len(budget_conflicts)
    metrics["physical_conflict_count"] = len(candidate_conflicts) + len(budget_conflicts)
    metrics["physical_budget_analysis"] = [budget.as_dict() for budget in budgets]
    metrics["physical_budget_matrix"] = list(metrics["physical_budget_analysis"])
    metrics["physical_feasibility"] = (
        "infeasible" if candidate_conflicts or budget_conflicts
        else "needs_measurement" if unknown_fields or any(
            budget.status == "needs_measurement" for budget in budgets
        )
        else "feasible" if physicals else "missing"
    )


def _record_physical_trade_study(metrics, decisions, physicals, rows, budgets):
    metrics["physical_feasibility_matrix"] = [
        rows[item.id] for item in physicals if item.id in rows
    ]
    metrics["physical_trade_study"] = [
        {
            "physical_id": item.id,
            "alternatives": list(item.payload.get("alternatives", ())),
            "selection_rationale": str(item.payload.get("selection_rationale", "")),
            "feasibility": item.payload.get("feasibility", {}),
            "constraint_evidence": rows.get(item.id, {}),
            "impact_chain": {
                "requirement_ids": rows.get(item.id, {}).get("requirement_ids", []),
                "function_ids": rows.get(item.id, {}).get("function_ids", []),
                "logical_ids": rows.get(item.id, {}).get("logical_ids", []),
                "physical_ids": [item.id],
            },
            "resolution_options": rows.get(item.id, {}).get("resolution_options", []),
        }
        for item in physicals
    ]
    if rows:
        best = max(rows.values(), key=lambda item: (float(item["score"]), item["physical_id"]))
        decisions.append({
            "step": "physical_feasibility_trade_study",
            "decision": (
                f"当前物理候选按约束证据评分最高为 {best['physical_id']} "
                f"({best['status']}, {best['score']} / 100)"
            ),
            "basis": [item["physical_id"] for item in rows.values()],
            "alternatives": list(rows.values()),
        })
    options = [
        {**dict(option), "physical_id": row["physical_id"]}
        for row in rows.values()
        for option in row.get("resolution_options", [])
    ]
    options.extend(
        {
            **dict(option),
            "physical_ids": list(option.get("physical_ids", budget.physical_ids)),
            "requirement_id": budget.requirement_id,
        }
        for budget in budgets
        if budget.conflicts and len(budget.physical_ids) > 1
        for option in budget.resolution_options
    )
    metrics["physical_resolution_options"] = options


def _violates(value, operator, limit):
    return operator == "max" and value > limit or operator == "min" and value < limit


def _active(index: Mapping[str, Entity], kind: EntityKind | None = None) -> tuple[Entity, ...]:
    return tuple(sorted(
        (
            item for item in index.values()
            if item.meta.status not in _INACTIVE and (kind is None or item.kind is kind)
        ),
        key=lambda item: item.id,
    ))


def _ready(index: Mapping[str, Entity], kind: EntityKind | None = None) -> tuple[Entity, ...]:
    return tuple(sorted(
        (
            item for item in index.values()
            if item.meta.status in _READY and (kind is None or item.kind is kind)
        ),
        key=lambda item: item.id,
    ))


def _relation_targets(
    graph,
    index,
    predicate: RelationPredicate,
    *,
    target_ready_only: bool = False,
):
    result = {}
    for relation in graph.relations:
        if relation.predicate is predicate and relation.source_id in index and relation.target_id in index:
            if index[relation.source_id].meta.status in _INACTIVE or index[relation.target_id].meta.status in _INACTIVE:
                continue
            if target_ready_only and index[relation.target_id].meta.status not in _READY:
                continue
            result.setdefault(relation.source_id, set()).add(relation.target_id)
    return {source: tuple(sorted(targets)) for source, targets in result.items()}


def _logical_decisions(component: Entity, function_ids: tuple[str, ...]):
    return (
        {
            "step": "dependency_clustering",
            "decision": str(component.payload.get("partition_basis", "按功能依赖形成逻辑分区")),
            "basis": list(function_ids),
        },
        {
            "step": "architecture_evaluation",
            "decision": (
                f"cohesion={component.payload.get('cohesion', 'unknown')}; "
                f"coupling={component.payload.get('coupling', 'unknown')}; "
                f"shared_state={component.payload.get('shared_state', [])}"
            ),
            "basis": [component.id, *function_ids],
        },
    )


def _logical_trade_study(functions, components, component_functions):
    function_ids = [item.id for item in functions]
    current_ids = [item.id for item in components]
    return [
        {
            "alternative": "current_dependency_partition",
            "component_ids": current_ids,
            "function_ids": function_ids,
            "rationale": "保留当前按依赖、共享状态和时序形成的边界",
        },
        {
            "alternative": "one_component_per_function",
            "component_ids": [],
            "function_ids": function_ids,
            "rationale": "隔离职责最强，但可能增加接口和耦合",
        },
        {
            "alternative": "shared_coordinator",
            "component_ids": current_ids[:1],
            "function_ids": function_ids,
            "rationale": "共享状态简单，但需要验证单点负载和安全隔离",
        },
    ] if functions else []


def _count_interface_crossings(graph, index, function_to_components) -> int:
    exchanges = _relation_targets(graph, index, RelationPredicate.EXCHANGES_WITH)
    count = 0
    for interface_id in {
        target for targets in exchanges.values() for target in targets
        if index[target].kind in {EntityKind.INTERFACE, EntityKind.FUNCTIONAL_FLOW}
    }:
        connected = {
            component_id
            for function_id, targets in exchanges.items()
            if interface_id in targets
            for component_id in function_to_components.get(function_id, ())
        }
        if len(connected) > 1:
            count += 1
    return count


def _partition_quality(components: Sequence[Entity]) -> str:
    if not components:
        return "missing"
    if all(
        component.payload.get("cohesion") == "high"
        and component.payload.get("coupling") in {"low", "controlled"}
        for component in components
    ):
        return "reviewed"
    return "needs_review"


def _logical_partition_review_message(crossings: int, safety_review: bool) -> str:
    reasons = []
    if crossings:
        reasons.append("逻辑架构存在跨组件交互")
    if safety_review:
        reasons.append("当前逻辑分区违反显式安全隔离约束")
    detail = "，且".join(reasons) if reasons else "逻辑架构的内聚/耦合或分区依据"
    return f"{detail}，仍需评审，不能直接视为已完成架构权衡。"


def _requirements_by_physical(graph, index, allocations):
    logicals_by_physical = {}
    for logical_id, targets in allocations.items():
        for physical_id in targets:
            if index[logical_id].kind is EntityKind.LOGICAL_COMPONENT and index[physical_id].kind is EntityKind.PHYSICAL_BLOCK:
                logicals_by_physical.setdefault(physical_id, set()).add(logical_id)
    functions_by_logical = {}
    for source_id, targets in allocations.items():
        if index[source_id].kind is EntityKind.FUNCTION:
            for logical_id in targets:
                if index[logical_id].kind is EntityKind.LOGICAL_COMPONENT:
                    functions_by_logical.setdefault(logical_id, set()).add(source_id)
    requirements_by_function = {}
    for requirement_id, function_ids in _relation_targets(
        graph, index, RelationPredicate.SATISFIED_BY
    ).items():
        if index[requirement_id].kind is not EntityKind.REQUIREMENT:
            continue
        for function_id in function_ids:
            if index[function_id].kind is EntityKind.FUNCTION:
                requirements_by_function.setdefault(function_id, set()).add(requirement_id)
    result = {}
    for physical_id, logical_ids in logicals_by_physical.items():
        function_ids = {
            function_id for logical_id in logical_ids
            for function_id in functions_by_logical.get(logical_id, ())
        }
        result[physical_id] = tuple(
            index[requirement_id]
            for function_id in function_ids
            for requirement_id in requirements_by_function.get(function_id, ())
            if index[requirement_id].kind is EntityKind.REQUIREMENT
        )
    return result


def _constraints(requirement: Entity):
    values = []
    containers = [requirement.payload]
    for key in ("constraints", "limits"):
        nested = requirement.payload.get(key)
        if isinstance(nested, Mapping):
            containers.append(nested)
    for container in containers:
        for key, raw in container.items():
            key_text = str(key)
            if key_text.startswith("max_"):
                number = _number(raw)
                if number is not None:
                    values.append((key_text[4:], "max", number))
            elif key_text.startswith("min_"):
                number = _number(raw)
                if number is not None:
                    values.append((key_text[4:], "min", number))
    unique = {}
    for field_name, operator, limit in values:
        unique[(field_name, operator)] = limit
    return tuple((field_name, operator, limit) for (field_name, operator), limit in sorted(unique.items()))


def _complete_vv_case(case: Entity) -> bool:
    return not missing_vv_plan_fields(case.payload)


def _requirement_ids_for_risks(risks, requirements, index, derived_from) -> set[str]:
    requirement_ids = {item.id for item in requirements}
    covered = set()
    for risk in risks:
        payload_ids = risk.payload.get("requirement_ids", ())
        if isinstance(payload_ids, Sequence) and not isinstance(payload_ids, (str, bytes)):
            covered.update(
                str(item) for item in payload_ids if str(item) in requirement_ids
            )
        covered.update(
            target_id for target_id in derived_from.get(risk.id, ())
            if target_id in requirement_ids
        )
    return covered


def _has_evidence(case: Entity) -> bool:
    if "execution_evidence_ids" in case.payload:
        return not _missing_value(case.payload.get("execution_evidence_ids"))
    return not _missing_value(case.payload.get("evidence_ids"))


def _branches(activity: Entity) -> tuple[str, ...]:
    values = []
    for key in ("branches", "failure_branches", "boundary_branches", "alternatives"):
        value = activity.payload.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            values.extend(str(item) for item in value if str(item).strip())
    return tuple(dict.fromkeys(values))


def _case_branches(cases) -> tuple[str, ...]:
    values = []
    for case in cases:
        for key in ("covered_branches", "branch_ids"):
            value = case.payload.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                values.extend(str(item) for item in value if str(item).strip())
    return tuple(dict.fromkeys(values))


def _missing_value(value: object) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0
