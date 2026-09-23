"""Repository-backed fault injection and recovery evidence for Agent Robustness."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
import json
import tempfile
from typing import Iterator, Mapping

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.entities import Entity, EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.domain.model import AddEntity, ModelGraph, Patch, Relate, UpdateEntity
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.closure import evaluate_strict_closure
from rflp_lite.methodology.contracts import Phase
from rflp_lite.methodology.tasks import task_catalog, task_spec_hash
from rflp_lite.methodology.workflow import WorkflowRunner
from rflp_lite.repository.sqlite import SQLiteModelRepository
from rflp_lite.runtime.rule_based import RuleRuntime
from tests.mbse_benchmark.validators.requirements import validate_requirements


FAULTS = (
    "missing_entity",
    "missing_relation",
    "wrong_predicate",
    "invalid_endpoint",
    "conflicting_requirement",
    "unsupported_numeric_claim",
    "stale_evidence",
    "missing_verification",
    "physical_infeasibility",
    "locked_user_edit_conflict",
)


@dataclass(frozen=True, slots=True)
class FaultDefinition:
    fault_id: str
    expected_detection: str
    expected_root: str
    repairable: bool


@dataclass(frozen=True, slots=True)
class FaultObservation:
    detected: bool
    root_cause_localized: bool
    repair_success: bool
    repair_rounds: int
    evidence: Mapping[str, object]
    unrelated_entity_change_count: int = 0
    requires_human_review: bool = False


FAULT_DEFINITIONS = tuple(
    FaultDefinition(
        fault,
        "repository rejection, Gate, or external verifier",
        "persisted fault evidence",
        fault not in {"locked_user_edit_conflict", "physical_infeasibility"},
    )
    for fault in FAULTS
)


def _gate_payload(result) -> dict[str, object]:
    return {
        "gate_id": result.gate_id,
        "passed": result.passed,
        "issues": [
            {"code": issue.code, "entity_ids": list(issue.entity_ids)}
            for issue in result.issues
        ],
        "checks": list(result.checks),
    }


def _graph_payload(graph: ModelGraph) -> dict[str, object]:
    return {
        "project_id": graph.project_id,
        "revision": graph.revision,
        "snapshot_hash": graph.snapshot_hash,
        "entities": [entity.as_dict() for entity in graph.entities],
        "relations": [
            {
                "id": relation.id,
                "source_id": relation.source_id,
                "predicate": relation.predicate.value,
                "target_id": relation.target_id,
                "evidence_ids": list(relation.evidence_ids),
            }
            for relation in graph.relations
        ],
    }


def _observation(
    detected: bool,
    localized: bool,
    repaired: bool,
    rounds: int,
    evidence: Mapping[str, object],
    *,
    requires_human_review: bool = False,
    unrelated_entity_change_count: int = 0,
) -> FaultObservation:
    return FaultObservation(
        detected,
        localized,
        repaired,
        rounds,
        dict(evidence),
        unrelated_entity_change_count=unrelated_entity_change_count,
        requires_human_review=requires_human_review,
    )


class _RepositoryExecution:
    """One lease-owned benchmark run using the production repository path."""

    def __init__(self, repository: SQLiteModelRepository, fault: str):
        self.repository = repository
        self.fault = fault
        self.project_id = f"robustness-{fault}"
        self.run_id = f"run-{fault}"
        self.runner = WorkflowRunner(repository, repository, RuleRuntime())
        self._issue_ids: tuple[str, ...] = ()

    def __enter__(self) -> "_RepositoryExecution":
        self.repository.ensure_project(self.project_id, self.project_id)
        identity = self.runner._ensure_run(
            self.project_id,
            run_id=self.run_id,
            phase=Phase.ASSURANCE,
        )
        self.run_id = identity.run_id
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.runner._release_lease(self.project_id, self.run_id)
        self.repository.close()

    def append(self, task_id: str, operations: tuple[object, ...], reason: str):
        graph = self.repository.load_graph(self.project_id)
        patch = Patch.create(
            self.project_id,
            task_id,
            operations,
            reason,
            graph.revision,
        )
        revision = self.runner._append_run_patch(
            self.project_id,
            patch,
            graph.revision,
            self.run_id,
        )
        return graph, revision, self.repository.load_graph(self.project_id)

    def gate(self, phase: Phase):
        result = self.runner.gate(self.project_id, phase, run_id=self.run_id)
        self._issue_ids = tuple(
            self.runner._issue_id(self.project_id, result, issue)
            for issue in result.issues
        )
        return result

    def resolve_gate_issues(self) -> None:
        self.runner._resolve_issues(self.project_id, set(self._issue_ids), self.run_id)

    def external_issue(self, code: str, entity_ids: tuple[str, ...], details: Mapping[str, object]) -> None:
        issue_id = f"{self.fault}-{code}"
        self.repository.save_issue(
            self.project_id,
            {
                "id": issue_id,
                "code": code,
                "severity": "error",
                "entity_ids": list(entity_ids),
                "run_id": self.run_id,
                "status": "open",
            },
        )
        self.repository.record_audit(
            self.project_id,
            "verifier.issue.detected",
            {"run_id": self.run_id, "fault_id": self.fault, "code": code, **dict(details)},
        )


@contextmanager
def _execution(fault: str) -> Iterator[_RepositoryExecution]:
    temporary = tempfile.TemporaryDirectory(prefix="ai4mbse-robustness-")
    repository = SQLiteModelRepository(Path(temporary.name) / "model.db")
    try:
        with _RepositoryExecution(repository, fault) as execution:
            yield execution
    finally:
        temporary.cleanup()


def _entity(
    kind: EntityKind,
    name: str,
    payload: Mapping[str, object] | None = None,
    *,
    status: EntityStatus = EntityStatus.ACCEPTED,
    producer: Producer = Producer.IMPORT,
) -> Entity:
    return make_entity(kind, name, payload or {}, status=status, producer=producer, confidence=1.0)


def _seed(
    execution: _RepositoryExecution,
    *,
    architecture: bool,
    vv: bool,
    two_requirements: bool = False,
    trace_predicate: RelationPredicate | None = RelationPredicate.SATISFIED_BY,
) -> tuple[Entity, ...]:
    requirements = [
        _entity(
            EntityKind.REQUIREMENT,
            "运行时间不得低于 12 小时",
            {"statement": "运行时间不得低于 12 小时", "metric": {"name": "runtime", "operator": ">=", "value": 12}},
        )
    ]
    if two_requirements:
        requirements.append(
            _entity(
                EntityKind.REQUIREMENT,
                "运行时间不得高于 8 小时",
                {"statement": "运行时间不得高于 8 小时", "metric": {"name": "runtime", "operator": "<=", "value": 8}},
            )
        )
    function = _entity(EntityKind.FUNCTION, "运行控制", {"behavior": "维持系统连续运行"})
    operations: list[object] = [*(AddEntity(item) for item in requirements), AddEntity(function)]
    if trace_predicate is not None:
        operations.extend(
            Relate(item.id, trace_predicate, function.id)
            for item in requirements
        )
    entities: list[Entity] = [*requirements, function]
    if architecture:
        logical = _entity(EntityKind.LOGICAL_COMPONENT, "运行控制逻辑组件", {"responsibility": "运行控制"})
        physical = _entity(EntityKind.PHYSICAL_BLOCK, "运行控制物理组件", {"mass": 2, "energy": 2400, "average_power": 200})
        operations.extend((AddEntity(logical), AddEntity(physical)))
        operations.extend((Relate(function.id, RelationPredicate.ALLOCATED_TO, logical.id), Relate(logical.id, RelationPredicate.ALLOCATED_TO, physical.id)))
        entities.extend((logical, physical))
        if vv:
            verification = _entity(
                EntityKind.VERIFICATION_CASE,
                "运行时间测试",
                {
                    "requirement_ids": [item.id for item in requirements],
                    "function_ids": [function.id],
                    "logical_component_ids": [logical.id],
                    "physical_ids": [physical.id],
                    "method": "test", "verification_objective": "验证连续运行时间",
                    "precondition": "系统处于可测试状态", "test_condition": "标准运行环境",
                    "input": "运行时间需求", "stimulus": "执行连续运行任务",
                    "procedure": "执行并记录运行时长", "expected_result": "运行时长达到需求",
                    "pass_criteria": "运行时间不少于 12 小时",
                },
            )
            validation = _entity(
                EntityKind.VALIDATION_CASE,
                "运行场景确认",
                {
                    "requirement_ids": [item.id for item in requirements],
                    "function_ids": [function.id],
                    "logical_component_ids": [logical.id],
                    "physical_ids": [physical.id],
                    "method": "demonstration", "verification_objective": "确认典型运行场景",
                    "precondition": "代表性用户场景可用", "test_condition": "真实运行环境",
                    "input": "运行任务", "stimulus": "用户执行典型任务",
                    "procedure": "执行场景并收集反馈", "expected_result": "用户目标达成",
                    "pass_criteria": "用户确认通过",
                },
            )
            operations.extend((AddEntity(verification), AddEntity(validation)))
            operations.extend(
                (Relate(item.id, RelationPredicate.VERIFIED_BY, verification.id),
                 Relate(item.id, RelationPredicate.VALIDATED_BY, validation.id))
                for item in requirements
            )
            entities.extend((verification, validation))
    execution.append("robustness.seed", tuple(operations), "seed golden graph")
    return tuple(entities)


def _entity_changes(before: ModelGraph, after: ModelGraph, related_ids: set[str]) -> int:
    before_by_id = {item.id: item for item in before.entities}
    changes = 0
    for entity in after.entities:
        if entity.id in related_ids:
            continue
        previous = before_by_id.get(entity.id)
        if previous is None or previous.content_hash != entity.content_hash:
            changes += 1
    return changes


def _numeric_conflicts(graph: ModelGraph) -> tuple[dict[str, object], ...]:
    rows: dict[str, list[tuple[str, str, float]]] = {}
    for entity in graph.entities:
        metric = entity.payload.get("metric")
        if entity.kind is not EntityKind.REQUIREMENT or not isinstance(metric, Mapping):
            continue
        name = str(metric.get("name", "")).strip()
        operator = str(metric.get("operator", "")).strip()
        if name and operator in {"<=", ">=", "<", ">"}:
            rows.setdefault(name, []).append((entity.id, operator, float(metric.get("value", 0))))
    conflicts: list[dict[str, object]] = []
    for metric, values in rows.items():
        lowers = [item for item in values if item[1] in {">=", ">"}]
        uppers = [item for item in values if item[1] in {"<=", "<"}]
        for lower in lowers:
            for upper in uppers:
                if lower[2] > upper[2]:
                    conflicts.append({"conflict_id": f"{metric}-conflict", "metric": metric, "lower": lower[2], "upper": upper[2], "entity_ids": [lower[0], upper[0]]})
    return tuple(conflicts)


def _physical_conflicts(graph: ModelGraph) -> tuple[dict[str, object], ...]:
    components = [item for item in graph.entities if item.kind is EntityKind.PHYSICAL_BLOCK]
    total_mass = sum(float(item.payload.get("mass", 0) or 0) for item in components)
    energy = sum(float(item.payload.get("energy", 0) or 0) for item in components)
    power = max((float(item.payload.get("average_power", 0) or 0) for item in components), default=0.0)
    conflicts: list[dict[str, object]] = []
    for requirement in graph.entities:
        metric = requirement.payload.get("metric")
        if requirement.kind is not EntityKind.REQUIREMENT or not isinstance(metric, Mapping):
            continue
        value = float(metric.get("value", 0) or 0)
        name = str(metric.get("name", ""))
        actual = total_mass if name in {"mass", "weight"} else energy / power if name == "runtime" and power else None
        if actual is None:
            continue
        operator = str(metric.get("operator", ""))
        passed = actual <= value if operator == "<=" else actual >= value if operator == ">=" else True
        if not passed:
            conflicts.append({"conflict_id": f"physical-{name}-conflict", "actual": actual, "limit": value, "entity_ids": [requirement.id, *(item.id for item in components)]})
    return tuple(conflicts)


def _detect(fault: str) -> FaultObservation:
    with _execution(fault) as execution:
        if fault == "missing_relation":
            entities = _seed(execution, architecture=False, vv=False, trace_predicate=None)
            before = execution.gate(Phase.FUNCTIONAL)
            before_graph = execution.repository.load_graph(execution.project_id)
            _, _, after_graph = execution.append("robustness.repair.missing_relation", (Relate(entities[0].id, RelationPredicate.SATISFIED_BY, entities[1].id),), "repair missing requirement trace")
            after = execution.gate(Phase.FUNCTIONAL)
            execution.resolve_gate_issues()
            return _observation(not before.passed, any(issue.code == "broken_requirement_function_trace" for issue in before.issues), after.passed, 1, {"repository": "SQLiteModelRepository", "lease_protected_cas": True, "gate_before": _gate_payload(before), "gate_after": _gate_payload(after), "rerun_verifier": after.passed}, unrelated_entity_change_count=_entity_changes(before_graph, after_graph, {entities[0].id, entities[1].id}))

        if fault == "wrong_predicate":
            entities = _seed(execution, architecture=False, vv=False, trace_predicate=RelationPredicate.DERIVED_FROM)
            before = execution.gate(Phase.FUNCTIONAL)
            before_graph = execution.repository.load_graph(execution.project_id)
            _, _, after_graph = execution.append("robustness.repair.wrong_predicate", (Relate(entities[0].id, RelationPredicate.SATISFIED_BY, entities[1].id),), "repair wrong trace predicate")
            after = execution.gate(Phase.FUNCTIONAL)
            execution.resolve_gate_issues()
            return _observation(not before.passed, any(issue.code == "broken_requirement_function_trace" for issue in before.issues), after.passed, 1, {"repository": "SQLiteModelRepository", "lease_protected_cas": True, "gate_before": _gate_payload(before), "gate_after": _gate_payload(after), "rerun_verifier": after.passed}, unrelated_entity_change_count=_entity_changes(before_graph, after_graph, {entities[0].id, entities[1].id}))

        if fault == "missing_entity":
            entities = _seed(execution, architecture=False, vv=False)
            try:
                execution.append("robustness.fault.missing_entity", (Relate(entities[0].id, RelationPredicate.SATISFIED_BY, "missing-target"),), "inject missing endpoint")
            except ContractViolation as exc:
                repaired_target = _entity(EntityKind.FUNCTION, "修复后的运行功能")
                before_graph = execution.repository.load_graph(execution.project_id)
                _, _, after_graph = execution.append("robustness.repair.missing_entity", (AddEntity(repaired_target), Relate(entities[0].id, RelationPredicate.SATISFIED_BY, repaired_target.id)), "repair missing endpoint")
                after = execution.gate(Phase.FUNCTIONAL)
                execution.resolve_gate_issues()
                return _observation(True, "endpoint" in str(exc).casefold() or "not found" in str(exc).casefold(), after.passed, 1, {"repository": "SQLiteModelRepository", "fault_injection_rejected": True, "injection_error": str(exc), "gate_after": _gate_payload(after), "rerun_verifier": after.passed}, unrelated_entity_change_count=_entity_changes(before_graph, after_graph, {entities[0].id, repaired_target.id}))

        if fault == "invalid_endpoint":
            entities = _seed(execution, architecture=True, vv=False)
            try:
                execution.append("robustness.fault.invalid_endpoint", (Relate(entities[0].id, RelationPredicate.VERIFIED_BY, entities[1].id),), "inject invalid relation endpoint")
            except ContractViolation as exc:
                verification = _entity(EntityKind.VERIFICATION_CASE, "修复后的运行时间测试", {
                    "requirement_ids": [entities[0].id], "function_ids": [entities[1].id],
                    "logical_component_ids": [entities[2].id], "physical_ids": [entities[3].id],
                    "method": "test", "verification_objective": "验证运行时间", "precondition": "系统可测试",
                    "test_condition": "标准环境", "input": "运行时间", "stimulus": "执行任务",
                    "procedure": "记录运行时长", "expected_result": "达到下限", "pass_criteria": "不少于 12 小时",
                })
                validation = _entity(EntityKind.VALIDATION_CASE, "修复后的运行场景确认", {
                    "requirement_ids": [entities[0].id], "function_ids": [entities[1].id],
                    "logical_component_ids": [entities[2].id], "physical_ids": [entities[3].id],
                    "method": "demonstration", "verification_objective": "确认运行场景", "precondition": "场景可用",
                    "test_condition": "真实环境", "input": "运行任务", "stimulus": "用户执行任务",
                    "procedure": "收集用户确认", "expected_result": "目标达成", "pass_criteria": "用户确认通过",
                })
                before_graph = execution.repository.load_graph(execution.project_id)
                _, _, after_graph = execution.append("robustness.repair.invalid_endpoint", (AddEntity(verification), AddEntity(validation), Relate(entities[0].id, RelationPredicate.VERIFIED_BY, verification.id), Relate(entities[0].id, RelationPredicate.VALIDATED_BY, validation.id)), "repair invalid relation endpoint")
                after = execution.gate(Phase.ASSURANCE)
                execution.resolve_gate_issues()
                return _observation(True, "endpoint type" in str(exc).casefold(), after.passed, 1, {"repository": "SQLiteModelRepository", "fault_injection_rejected": True, "injection_error": str(exc), "gate_after": _gate_payload(after), "rerun_verifier": after.passed}, unrelated_entity_change_count=_entity_changes(before_graph, after_graph, {entities[0].id, verification.id, validation.id}))

        if fault == "missing_verification":
            entities = _seed(execution, architecture=True, vv=False)
            before = execution.gate(Phase.ASSURANCE)
            before_graph = execution.repository.load_graph(execution.project_id)
            verification = _entity(EntityKind.VERIFICATION_CASE, "修复后的运行时间测试", {
                "requirement_ids": [entities[0].id], "function_ids": [entities[1].id],
                "logical_component_ids": [entities[2].id], "physical_ids": [entities[3].id],
                "method": "test", "verification_objective": "验证运行时间", "precondition": "系统可测试",
                "test_condition": "标准环境", "input": "运行时间", "stimulus": "执行任务",
                "procedure": "记录运行时长", "expected_result": "达到下限", "pass_criteria": "不少于 12 小时",
            })
            validation = _entity(EntityKind.VALIDATION_CASE, "修复后的运行场景确认", {
                "requirement_ids": [entities[0].id], "function_ids": [entities[1].id],
                "logical_component_ids": [entities[2].id], "physical_ids": [entities[3].id],
                "method": "demonstration", "verification_objective": "确认运行场景", "precondition": "场景可用",
                "test_condition": "真实环境", "input": "运行任务", "stimulus": "用户执行任务",
                "procedure": "收集用户确认", "expected_result": "目标达成", "pass_criteria": "用户确认通过",
            })
            _, _, after_graph = execution.append("robustness.repair.missing_verification", (AddEntity(verification), AddEntity(validation), Relate(entities[0].id, RelationPredicate.VERIFIED_BY, verification.id), Relate(entities[0].id, RelationPredicate.VALIDATED_BY, validation.id)), "repair missing V&V trace")
            after = execution.gate(Phase.ASSURANCE)
            execution.resolve_gate_issues()
            return _observation(not before.passed, any(issue.code in {"missing_verification", "broken_requirement_verification_trace"} for issue in before.issues), after.passed, 1, {"repository": "SQLiteModelRepository", "lease_protected_cas": True, "gate_before": _gate_payload(before), "gate_after": _gate_payload(after), "rerun_verifier": after.passed, "closure_after": evaluate_strict_closure(after_graph).as_dict()}, unrelated_entity_change_count=_entity_changes(before_graph, after_graph, {entities[0].id, verification.id, validation.id}))

        if fault == "conflicting_requirement":
            _seed(execution, architecture=False, vv=False, two_requirements=True)
            graph = execution.repository.load_graph(execution.project_id)
            conflicts = _numeric_conflicts(graph)
            execution.external_issue("numeric_requirement_conflict", tuple(conflicts[0]["entity_ids"]) if conflicts else (), {"conflicts": list(conflicts)})
            return _observation(bool(conflicts), bool(conflicts), False, 0, {"repository": "SQLiteModelRepository", "verifier": "numeric-conflict-evaluator", "conflicts": list(conflicts)}, requires_human_review=True)

        if fault == "unsupported_numeric_claim":
            _seed(execution, architecture=False, vv=False)
            hard = _entity(EntityKind.REQUIREMENT, "必须使用64线激光雷达", {"statement": "必须使用64线激光雷达", "metric": {"value": 64}})
            execution.append("robustness.fault.unsupported_numeric_claim", (AddEntity(hard),), "inject unsupported hard claim")
            report = validate_requirements(_graph_payload(execution.repository.load_graph(execution.project_id)))
            finding = next(item for item in report["findings"] if item.get("test_id") == "T19")
            detected = finding.get("status") == "FAIL"
            execution.external_issue("unsupported_hard_assumption", (hard.id,), {"finding": finding})
            return _observation(detected, detected, False, 0, {"repository": "SQLiteModelRepository", "verifier": "requirements-validator", "finding": finding}, requires_human_review=True)

        if fault == "stale_evidence":
            entities = _seed(execution, architecture=False, vv=False)
            execution.append("robustness.fault.stale_evidence", (Relate(entities[0].id, RelationPredicate.SATISFIED_BY, entities[1].id, ("evidence-missing",)),), "inject stale evidence reference")
            graph = execution.repository.load_graph(execution.project_id)
            known = {entity.id for entity in graph.entities} | {str(item.get("id")) for item in execution.repository.list_evidence(execution.project_id)}
            stale = tuple(sorted({evidence_id for relation in graph.relations for evidence_id in relation.evidence_ids if evidence_id not in known}))
            execution.external_issue("stale_evidence_reference", (entities[0].id, entities[1].id), {"missing_evidence_ids": list(stale)})
            return _observation(bool(stale), bool(stale), False, 0, {"repository": "SQLiteModelRepository", "verifier": "evidence-reference-check", "missing_evidence_ids": list(stale)}, requires_human_review=True)

        if fault == "physical_infeasibility":
            req_weight = _entity(EntityKind.REQUIREMENT, "整车重量不得超过 20 kg", {"metric": {"name": "mass", "operator": "<=", "value": 20}})
            req_runtime = _entity(EntityKind.REQUIREMENT, "连续运行时间不得低于 12 小时", {"metric": {"name": "runtime", "operator": ">=", "value": 12}})
            components = tuple(_entity(EntityKind.PHYSICAL_BLOCK, name, payload) for name, payload in (("电池", {"mass": 15, "energy": 1000, "average_power": 200}), ("底盘", {"mass": 8}), ("电机", {"mass": 4}), ("传感器", {"mass": 3}), ("计算平台", {"mass": 2})))
            execution.append("robustness.fault.physical_infeasibility", tuple(AddEntity(item) for item in (req_weight, req_runtime, *components)), "inject infeasible physical design")
            conflicts = _physical_conflicts(execution.repository.load_graph(execution.project_id))
            execution.external_issue("physical_feasibility_conflict", tuple(item for conflict in conflicts for item in conflict["entity_ids"]), {"conflicts": list(conflicts)})
            return _observation(bool(conflicts), bool(conflicts), False, 0, {"repository": "SQLiteModelRepository", "verifier": "physical-feasibility-evaluator", "conflicts": list(conflicts)}, requires_human_review=True)

        if fault == "locked_user_edit_conflict":
            locked = _entity(EntityKind.REQUIREMENT, "锁定需求", {}, status=EntityStatus.LOCKED, producer=Producer.USER)
            execution.append("robustness.fault.locked_user_edit_conflict", (AddEntity(locked),), "seed locked user entity")
            try:
                execution.append("robustness.fault.locked_user_edit_conflict", (UpdateEntity(locked.id, {"name": "越权修改"}),), "attempt locked user edit")
            except ContractViolation as exc:
                execution.external_issue("locked_edit_conflict", (locked.id,), {"error": str(exc)})
                return _observation(True, "locked" in str(exc).casefold(), False, 0, {"repository": "SQLiteModelRepository", "cas_and_lifecycle_rejection": True, "error": str(exc)}, requires_human_review=True)

        return _observation(False, False, False, 0, {"repository": "SQLiteModelRepository"})


def run_robustness_benchmark() -> dict[str, object]:
    results: list[dict[str, object]] = []
    for definition in FAULT_DEFINITIONS:
        started = monotonic()
        observation = _detect(definition.fault_id)
        results.append({
            "fault_id": definition.fault_id,
            "repairable": definition.repairable,
            "detected": observation.detected,
            "root_cause_localized": observation.root_cause_localized,
            "repair_success": observation.repair_success if definition.repairable else False,
            "requires_human_review": observation.requires_human_review or not definition.repairable,
            "repair_rounds": observation.repair_rounds,
            "unrelated_entity_change_count": observation.unrelated_entity_change_count,
            "evidence": dict(observation.evidence),
            "token_cost": None,
            "latency_ms": round((monotonic() - started) * 1000, 3),
        })
    count = len(results)
    repairable_results = [item for item in results if item["repairable"]]
    metrics = {
        "detection_rate": sum(bool(item["detected"]) for item in results) / count,
        "root_cause_localization_rate": sum(bool(item["root_cause_localized"]) for item in results) / count,
        "repair_success_rate": sum(bool(item["repair_success"]) for item in repairable_results) / len(repairable_results),
        "mean_repair_rounds": sum(int(item["repair_rounds"]) for item in results) / count,
        "regression_rate": sum(int(item["unrelated_entity_change_count"]) for item in results) / count,
        "unrelated_entity_change_count": sum(int(item["unrelated_entity_change_count"]) for item in results),
        "token_cost": None,
        "latency": round(sum(float(item["latency_ms"]) for item in results), 3),
    }
    return {
        "track": "robustness",
        "runtime": "WorkflowRunner + RuleRuntime",
        "model_profile": "offline-rule",
        "provider": "offline",
        "model": "rule-runtime",
        "methodology_version": "v2.1",
        "prompt_hash": "not_applicable",
        "task_spec_hash": canonical_hash(tuple(task_spec_hash(task) for task in task_catalog())),
        "commit": _git_commit(),
        "case": "fault-suite",
        "repeat": 1,
        "faults": list(FAULTS),
        "metrics": metrics,
        "case_results": results,
        "status": "PASS" if metrics["detection_rate"] == 1.0 and metrics["root_cause_localization_rate"] == 1.0 else "FAIL",
    }


def _git_commit() -> str:
    try:
        import subprocess
        return subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip() or "unknown"
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def write_robustness_report(summary: Mapping[str, object], report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    metrics = summary.get("metrics", {})
    lines = [
        "# Agent Robustness Benchmark", "",
        f"Track: **{summary.get('track', 'robustness')}**",
        f"Runtime: **{summary.get('runtime', 'WorkflowRunner + RuleRuntime')}**",
        f"Profile/provider/model: **{summary.get('model_profile', 'offline-rule')} / {summary.get('provider', 'offline')} / {summary.get('model', 'rule-runtime')}**",
        f"Methodology version: **{summary.get('methodology_version', '')}**",
        f"Prompt/task-spec hash: **{summary.get('prompt_hash', '')} / {summary.get('task_spec_hash', '')}**",
        f"Commit/case/repeat: **{summary.get('commit', 'unknown')} / {summary.get('case', 'fault-suite')} / {summary.get('repeat', 1)}**",
        f"Status: **{summary.get('status', 'FAIL')}**", "",
        "| Fault | Detected | Root localized | Repair success | Human review | Rounds |",
        "| ----- | -------- | -------------- | -------------- | ------------ | ------ |",
    ]
    for item in summary.get("case_results", ()):
        lines.append(
            f"| {item.get('fault_id', '')} | {item.get('detected', False)} | "
            f"{item.get('root_cause_localized', False)} | {item.get('repair_success', False)} | "
            f"{item.get('requires_human_review', False)} | {item.get('repair_rounds', 0)} |"
        )
    (report_dir / "robustness_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (report_dir / "metrics.json").write_text(json.dumps({"metadata": {
        "track": summary.get("track"), "runtime": summary.get("runtime"), "model_profile": summary.get("model_profile"),
        "provider": summary.get("provider"), "model": summary.get("model"), "methodology_version": summary.get("methodology_version"),
        "prompt_hash": summary.get("prompt_hash"), "task_spec_hash": summary.get("task_spec_hash"), "commit": summary.get("commit"),
        "case": summary.get("case"), "repeat": summary.get("repeat"),
    }, "metrics": metrics}, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (report_dir / "failures.json").write_text(json.dumps([
        item for item in summary.get("case_results", ()) if not item.get("detected", False)
    ], ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
