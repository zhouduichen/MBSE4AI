"""Deterministic systems-engineering analysis over the semantic ModelGraph."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from rflp_lite.domain.entities import Entity, EntityKind, EntityStatus
from rflp_lite.domain.model import ModelGraph
from rflp_lite.domain.relations import RelationPredicate


_INACTIVE = frozenset({EntityStatus.REJECTED, EntityStatus.DEPRECATED})
_PHYSICAL_FIELDS = (
    "mass_kg", "power_w", "compute", "memory_mb", "latency_ms",
    "bandwidth_mbps", "cost", "thermal", "reliability", "availability",
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
    EntityKind.PHYSICAL_BLOCK: (
        "physical_candidates", "constraint_propagation", "feasibility_selection",
        "verification_validation",
    ),
    EntityKind.VERIFICATION_CASE: ("verification_validation", "global_cross_analysis"),
    EntityKind.VALIDATION_CASE: ("verification_validation", "global_cross_analysis"),
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
        self._analyze_logical(graph, index, findings, decisions, metrics)
        self._analyze_physical(graph, index, findings, metrics)
        self._analyze_vv(graph, index, findings, decisions, metrics)
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

    def _analyze_logical(self, graph, index, findings, decisions, metrics) -> None:
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

    def _analyze_physical(self, graph, index, findings, metrics) -> None:
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
        metrics["physical_trade_study"] = [
            {
                "physical_id": item.id,
                "alternatives": list(item.payload.get("alternatives", ())),
                "selection_rationale": str(item.payload.get("selection_rationale", "")),
                "feasibility": item.payload.get("feasibility", {}),
            }
            for item in physicals
        ]

    def _analyze_vv(self, graph, index, findings, decisions, metrics) -> None:
        requirements = _active(index, EntityKind.REQUIREMENT)
        verifications = _relation_targets(graph, index, RelationPredicate.VERIFIED_BY)
        validations = _relation_targets(graph, index, RelationPredicate.VALIDATED_BY)
        verification_count = 0
        validation_count = 0
        structured_verification = 0
        structured_validation = 0
        verification_evidence = 0
        validation_evidence = 0
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


def _has_evidence(case: Entity) -> bool:
    return not _missing_value(case.payload.get("evidence_ids"))


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
