"""Deterministic systems-engineering analysis over the semantic ModelGraph."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from rflp_lite.domain.entities import Entity, EntityKind, EntityStatus
from rflp_lite.domain.model import ModelGraph
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.architecture_synthesis import (
    ArchitectureSynthesis,
    synthesize_architecture,
)
from rflp_lite.methodology.trace_rules import is_technical_requirement


_INACTIVE = frozenset({EntityStatus.REJECTED, EntityStatus.DEPRECATED})
_PHYSICAL_FIELDS = (
    "mass_kg", "power_w", "compute", "memory_mb", "latency_ms",
    "bandwidth_mbps", "cost", "thermal", "reliability", "availability", "endurance_h",
)
_OPERATIONAL_KINDS = (
    EntityKind.SYSTEM, EntityKind.STAKEHOLDER, EntityKind.CONCERN,
    EntityKind.LIFECYCLE_STAGE,
    EntityKind.SCENARIO_HYPOTHESIS, EntityKind.USE_CASE,
    EntityKind.OPERATIONAL_SCENARIO, EntityKind.ACTIVITY, EntityKind.REQUIREMENT,
)
_VV_PLAN_FIELDS = (
    "method", "precondition", "input", "procedure", "expected_result",
    "pass_criteria",
)
_STAGE_ORDER = ("requirements", "functional", "logical", "physical", "assurance")
_TASK_ORDER = (
    "system_requirement_derivation", "function_identification", "functional_decomposition",
    "functional_interaction", "logical_analysis", "dependency_clustering",
    "architecture_evaluation", "physical_candidates", "allocation_tradeoff",
    "constraint_propagation", "feasibility_selection", "verification_validation",
    "reverse_feasibility", "global_cross_analysis",
)
_TASKS_BY_KIND = {
    EntityKind.CONCERN: (
        "stakeholder_analysis", "system_requirement_derivation",
    ),
    EntityKind.REQUIREMENT: (
        "system_requirement_derivation", "function_identification", "logical_analysis",
        "physical_candidates", "verification_validation",
    ),
    EntityKind.FUNCTION: (
        "functional_decomposition", "functional_interaction", "logical_analysis",
        "physical_candidates", "verification_validation",
    ),
    EntityKind.LOGICAL_COMPONENT: (
        "logical_analysis", "dependency_clustering", "architecture_evaluation",
        "physical_candidates", "verification_validation",
    ),
    EntityKind.STATE: (
        "interface_sequence_state", "logical_analysis", "verification_validation",
    ),
    EntityKind.PHYSICAL_BLOCK: (
        "physical_candidates", "constraint_propagation", "feasibility_selection",
        "verification_validation",
    ),
    EntityKind.VERIFICATION_CASE: ("verification_validation", "global_cross_analysis"),
    EntityKind.VALIDATION_CASE: ("verification_validation", "global_cross_analysis"),
    EntityKind.HAZARD: (
        "fmea_stpa_hazard", "verification_validation", "global_cross_analysis",
    ),
    EntityKind.FAILURE_MODE: (
        "fmea_stpa_hazard", "reverse_feasibility", "global_cross_analysis",
    ),
}
_KIND_STAGES = {
    EntityKind.SYSTEM: "requirements",
    EntityKind.STAKEHOLDER: "requirements",
    EntityKind.CONCERN: "requirements",
    EntityKind.LIFECYCLE_STAGE: "requirements",
    EntityKind.SCENARIO_HYPOTHESIS: "requirements",
    EntityKind.USE_CASE: "requirements",
    EntityKind.OPERATIONAL_SCENARIO: "requirements",
    EntityKind.ACTIVITY: "requirements",
    EntityKind.REQUIREMENT: "requirements",
    EntityKind.FUNCTION: "functional",
    EntityKind.FUNCTIONAL_FLOW: "functional",
    EntityKind.FUNCTIONAL_SCENARIO: "functional",
    EntityKind.LOGICAL_COMPONENT: "logical",
    EntityKind.INTERFACE: "logical",
    EntityKind.PHYSICAL_BLOCK: "physical",
    EntityKind.STATE: "logical",
    EntityKind.HAZARD: "assurance",
    EntityKind.FAILURE_MODE: "assurance",
    EntityKind.VERIFICATION_CASE: "assurance",
    EntityKind.VALIDATION_CASE: "assurance",
    EntityKind.EVIDENCE: "assurance",
}


@dataclass(frozen=True, slots=True)
class MethodologyFinding:
    code: str
    severity: str
    stage: str
    entity_ids: tuple[str, ...] = ()
    message: str = ""
    recommended_actions: tuple[str, ...] = ()

    def as_dict(self) -> Mapping[str, object]:
        return {
            "code": self.code,
            "severity": self.severity,
            "stage": self.stage,
            "entity_ids": list(self.entity_ids),
            "message": self.message,
            "recommended_actions": list(self.recommended_actions),
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
        functions = _active(index, EntityKind.FUNCTION)
        flows = _active(index, EntityKind.FUNCTIONAL_FLOW)
        scenarios = _active(index, EntityKind.FUNCTIONAL_SCENARIO)
        satisfied = _relation_targets(graph, index, RelationPredicate.SATISFIED_BY)
        requirement_functions = {
            requirement.id: tuple(
                target for target in satisfied.get(requirement.id, ())
                if index[target].kind is EntityKind.FUNCTION
            )
            for requirement in requirements
        }
        function_flows = _relation_targets(graph, index, RelationPredicate.EXCHANGES_WITH)
        function_scenarios = _relation_targets(graph, index, RelationPredicate.DERIVED_FROM)
        covered_requirements = sum(bool(targets) for targets in requirement_functions.values())
        covered_functions = sum(bool(
            [target for target in function_flows.get(function.id, ()) if index[target].kind is EntityKind.FUNCTIONAL_FLOW]
        ) for function in functions)
        scenario_functions = sum(bool(
            [target for target in function_scenarios.get(function.id, ()) if index[target].kind is EntityKind.FUNCTIONAL_SCENARIO]
        ) for function in functions)
        metrics["functional_requirement_coverage"] = _ratio(covered_requirements, len(requirements))
        metrics["functional_flow_coverage"] = _ratio(covered_functions, len(functions))
        metrics["functional_scenario_coverage"] = _ratio(scenario_functions, len(functions))
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
        functions = _active(index, EntityKind.FUNCTION)
        components = _active(index, EntityKind.LOGICAL_COMPONENT)
        allocations = _relation_targets(graph, index, RelationPredicate.ALLOCATED_TO)
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
        states = _active(index, EntityKind.STATE)
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
        metrics["logical_partition_quality"] = _partition_quality(components)
        if components and metrics["logical_partition_quality"] == "needs_review":
            findings.append(MethodologyFinding(
                "logical_partition_needs_review", "warning", "logical",
                tuple(item.id for item in components),
                "逻辑架构的内聚/耦合或分区依据仍需评审，不能直接视为已完成架构权衡。",
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
        logicals = _active(index, EntityKind.LOGICAL_COMPONENT)
        physicals = _active(index, EntityKind.PHYSICAL_BLOCK)
        allocations = _relation_targets(graph, index, RelationPredicate.ALLOCATED_TO)
        logical_to_physical = {
            logical.id: tuple(
                target for target in allocations.get(logical.id, ())
                if index[target].kind is EntityKind.PHYSICAL_BLOCK
            )
            for logical in logicals
        }
        assigned = {item.id for item in logicals if logical_to_physical[item.id]}
        metrics["physical_logical_count"] = len(logicals)
        metrics["physical_block_count"] = len(physicals)
        metrics["physical_allocation_coverage"] = _ratio(len(assigned), len(logicals))
        for logical in logicals:
            if not logical_to_physical[logical.id]:
                findings.append(MethodologyFinding(
                    "physical_logical_unallocated", "warning", "physical", (logical.id,),
                    f"逻辑组件“{logical.meta.name}”没有物理实现候选。",
                    ("physical_candidates", "allocation_tradeoff"),
                ))
        requirements_by_physical = _requirements_by_physical(graph, index, allocations)
        unknown_fields = 0
        conflicts = []
        for physical in physicals:
            missing = tuple(field for field in _PHYSICAL_FIELDS if _missing_value(physical.payload.get(field)))
            unknown_fields += len(missing)
            constraints = tuple(
                (requirement, field_name, operator, limit)
                for requirement in requirements_by_physical.get(physical.id, ())
                for field_name, operator, limit in _constraints(requirement)
            )
            for requirement, field_name, operator, limit in constraints:
                value = _number(physical.payload.get(field_name))
                if value is None:
                    continue
                if operator == "max" and value > limit or operator == "min" and value < limit:
                    conflicts.append((requirement, physical, field_name, operator, limit, value))
        for requirement, physical, field_name, operator, limit, value in conflicts:
            findings.append(MethodologyFinding(
                "physical_constraint_conflict", "error", "physical",
                (requirement.id, physical.id),
                f"物理候选“{physical.meta.name}”的 {field_name}={value} 不满足 {operator}={limit} 约束。",
                ("constraint_propagation", "feasibility_selection", "allocation_tradeoff"),
            ))
        if unknown_fields:
            findings.append(MethodologyFinding(
                "physical_measurement_required", "warning", "physical",
                tuple(item.id for item in physicals),
                f"物理候选仍有 {unknown_fields} 个 SWaP-C/工程字段需要测量或证据。",
                ("physical_candidates", "feasibility_selection"),
            ))
        metrics["physical_unknown_field_count"] = unknown_fields
        metrics["physical_conflict_count"] = len(conflicts)
        metrics["physical_feasibility"] = (
            "infeasible" if conflicts else
            "needs_measurement" if unknown_fields else
            "feasible" if physicals else "missing"
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
        metrics["physical_trade_study"] = [
            {
                "physical_id": item.id,
                "alternatives": list(item.payload.get("alternatives", ())),
                "selection_rationale": str(item.payload.get("selection_rationale", "")),
                "feasibility": item.payload.get("feasibility", {}),
                "constraint_evidence": feasibility_rows.get(item.id, {}),
            }
            for item in physicals
        ]
        if feasibility_rows:
            best = max(
                feasibility_rows.values(),
                key=lambda item: (float(item["score"]), item["physical_id"]),
            )
            decisions.append({
                "step": "physical_feasibility_trade_study",
                "decision": (
                    f"当前物理候选按约束证据评分最高为 {best['physical_id']} "
                    f"({best['status']}, {best['score']} / 100)"
                ),
                "basis": [item["physical_id"] for item in feasibility_rows.values()],
                "alternatives": list(feasibility_rows.values()),
            })
        metrics["physical_resolution_options"] = [
            {
                "option": "降低计算或功耗需求",
                "task": "constraint_propagation",
                "impact": "可能影响功能性能需求",
            },
            {
                "option": "更换物理候选或计算架构",
                "task": "allocation_tradeoff",
                "impact": "保持需求但重新分配实现",
            },
            {
                "option": "调整需求约束或资源预算",
                "task": "system_requirement_derivation",
                "impact": "需要用户和利益相关者确认",
            },
            {
                "option": "增加电池质量或资源预算",
                "task": "system_requirement_derivation",
                "impact": "需要重新评估质量、续航和利益相关者约束",
            },
        ] if conflicts else []

    def _analyze_vv(self, graph, index, findings, decisions, metrics) -> None:
        requirements = _active(index, EntityKind.REQUIREMENT)
        hazards = _active(index, EntityKind.HAZARD)
        failure_modes = _active(index, EntityKind.FAILURE_MODE)
        verifications = _relation_targets(graph, index, RelationPredicate.VERIFIED_BY)
        validations = _relation_targets(graph, index, RelationPredicate.VALIDATED_BY)
        derived_from = _relation_targets(graph, index, RelationPredicate.DERIVED_FROM)
        mitigations = _relation_targets(graph, index, RelationPredicate.MITIGATED_BY)
        verification_count = 0
        validation_count = 0
        structured_verification = 0
        structured_validation = 0
        verification_evidence = 0
        validation_evidence = 0
        activities = _active(index, EntityKind.ACTIVITY)
        branch_names = tuple(
            branch
            for activity in activities
            for branch in _branches(activity)
        )
        covered_branches = set()
        hazard_requirement_ids = _requirement_ids_for_risks(
            hazards, requirements, index, derived_from
        )
        failure_requirement_ids = _requirement_ids_for_risks(
            failure_modes, requirements, index, derived_from
        )
        risk_requirement_ids = {
            requirement_id for requirement_id in hazard_requirement_ids | failure_requirement_ids
        }
        metrics["hazard_count"] = len(hazards)
        metrics["failure_mode_count"] = len(failure_modes)
        metrics["hazard_requirement_coverage"] = _ratio(
            len(hazard_requirement_ids), len(requirements)
        )
        metrics["failure_mode_requirement_coverage"] = _ratio(
            len(failure_requirement_ids), len(requirements)
        )
        metrics["hazard_failure_mode_coverage"] = _ratio(
            len(risk_requirement_ids), len(requirements)
        )
        for requirement in requirements:
            if requirement.id not in hazard_requirement_ids:
                findings.append(MethodologyFinding(
                    "hazard_analysis_missing", "warning", "assurance", (requirement.id,),
                    f"需求“{requirement.meta.name}”没有关联 Hazard 分析。",
                    ("fmea_stpa_hazard",),
                ))
            if requirement.id not in failure_requirement_ids:
                findings.append(MethodologyFinding(
                    "failure_mode_missing", "warning", "assurance", (requirement.id,),
                    f"需求“{requirement.meta.name}”没有关联 FailureMode 分析。",
                    ("fmea_stpa_hazard", "reverse_feasibility"),
                ))
        for risk in (*hazards, *failure_modes):
            if not any(
                index[target_id].kind in {
                    EntityKind.REQUIREMENT,
                    EntityKind.FUNCTION,
                    EntityKind.VERIFICATION_CASE,
                }
                for target_id in mitigations.get(risk.id, ())
            ):
                findings.append(MethodologyFinding(
                    "risk_without_mitigation", "warning", "assurance", (risk.id,),
                    f"风险对象“{risk.meta.name}”没有关联需求、功能或 VerificationCase 缓解措施。",
                    ("fmea_stpa_hazard", "verification_validation"),
                ))
        for requirement in requirements:
            verification_cases = tuple(
                index[item] for item in verifications.get(requirement.id, ())
                if index[item].kind is EntityKind.VERIFICATION_CASE
            )
            validation_cases = tuple(
                index[item] for item in validations.get(requirement.id, ())
                if index[item].kind is EntityKind.VALIDATION_CASE
            )
            verification_count += bool(verification_cases)
            validation_count += bool(validation_cases)
            if verification_cases:
                structured_verification += any(_complete_vv_case(item) for item in verification_cases)
                verification_evidence += any(_has_evidence(item) for item in verification_cases)
                covered_branches.update(_case_branches(verification_cases))
                self._vv_findings("verification", verification_cases, findings)
            else:
                findings.append(MethodologyFinding(
                    "verification_missing", "warning", "assurance", (requirement.id,),
                    f"需求“{requirement.meta.name}”没有 VerificationCase。",
                    ("verification_validation",),
                ))
            if validation_cases:
                structured_validation += any(_complete_vv_case(item) for item in validation_cases)
                validation_evidence += any(_has_evidence(item) for item in validation_cases)
                covered_branches.update(_case_branches(validation_cases))
                self._vv_findings("validation", validation_cases, findings)
            else:
                findings.append(MethodologyFinding(
                    "validation_missing", "warning", "assurance", (requirement.id,),
                    f"需求“{requirement.meta.name}”没有 ValidationCase。",
                    ("verification_validation",),
                ))
        verification_coverage = _ratio(verification_count, len(requirements))
        validation_coverage = _ratio(validation_count, len(requirements))
        metrics["verification_coverage"] = verification_coverage
        metrics["validation_coverage"] = validation_coverage
        metrics["structured_verification_coverage"] = _ratio(structured_verification, len(requirements))
        metrics["structured_validation_coverage"] = _ratio(structured_validation, len(requirements))
        metrics["verification_evidence_coverage"] = _ratio(verification_evidence, len(requirements))
        metrics["validation_evidence_coverage"] = _ratio(validation_evidence, len(requirements))
        metrics["activity_branch_coverage"] = (
            _ratio(len(set(branch_names) & covered_branches), len(set(branch_names)))
            if branch_names else 1.0
        )
        if branch_names and set(branch_names) - covered_branches:
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
        ))

    @staticmethod
    def _vv_findings(label, cases, findings) -> None:
        for case in cases:
            missing = tuple(field for field in _VV_PLAN_FIELDS if _missing_value(case.payload.get(field)))
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
    def _impact(graph, index, changed_entity_ids):
        seeds = tuple(sorted({item for item in changed_entity_ids if item in index}))
        if not seeds:
            return (), (), (), ()
        neighbors = {item.id: set() for item in _active(index)}
        for relation in graph.relations:
            if relation.source_id in neighbors and relation.target_id in neighbors:
                neighbors[relation.source_id].add(relation.target_id)
                neighbors[relation.target_id].add(relation.source_id)
        queue = deque((seed, (seed,), 0) for seed in seeds)
        visited = set(seeds)
        paths = []
        while queue:
            entity_id, path, depth = queue.popleft()
            paths.append(path)
            if depth >= 4:
                continue
            for neighbor in sorted(neighbors.get(entity_id, ())):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                queue.append((neighbor, path + (neighbor,), depth + 1))
        stages = tuple(sorted({
            _KIND_STAGES.get(index[item].kind, "unknown")
            for item in visited
        }, key=lambda item: _STAGE_ORDER.index(item) if item in _STAGE_ORDER else len(_STAGE_ORDER)))
        task_set = {
            task for item in visited for task in _TASKS_BY_KIND.get(index[item].kind, ())
        }
        tasks = tuple(task for task in _TASK_ORDER if task in task_set)
        return tuple(sorted(visited)), stages, tasks, tuple(paths)


def _active(index: Mapping[str, Entity], kind: EntityKind | None = None) -> tuple[Entity, ...]:
    return tuple(sorted(
        (
            item for item in index.values()
            if item.meta.status not in _INACTIVE and (kind is None or item.kind is kind)
        ),
        key=lambda item: item.id,
    ))


def _relation_targets(graph, index, predicate: RelationPredicate):
    result = {}
    for relation in graph.relations:
        if relation.predicate is predicate and relation.source_id in index and relation.target_id in index:
            if index[relation.source_id].meta.status in _INACTIVE or index[relation.target_id].meta.status in _INACTIVE:
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
    return all(not _missing_value(case.payload.get(field)) for field in _VV_PLAN_FIELDS)


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
