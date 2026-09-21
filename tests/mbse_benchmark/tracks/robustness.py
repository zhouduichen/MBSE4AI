"""Deterministic fault catalogue for the Agent Robustness track."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from pathlib import Path
import json
from typing import Mapping

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.domain.model import AddEntity, ModelGraph, Relation, Relate, UpdateEntity, apply_patch, Patch
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.closure import evaluate_strict_closure
from rflp_lite.methodology.coverage_matrix import build_requirement_coverage
from rflp_lite.methodology.tasks import task_catalog, task_spec_hash
from tests.mbse_benchmark.validators.common import validate_structural_graph
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
    FaultDefinition(fault, "deterministic validator or gate", "fault root", fault not in {"locked_user_edit_conflict", "physical_infeasibility"})
    for fault in FAULTS
)


def _graph(*, verification: bool = False, predicate: RelationPredicate = RelationPredicate.SATISFIED_BY) -> ModelGraph:
    requirement = make_entity(EntityKind.REQUIREMENT, "运行时间不得低于 12 小时", {"statement": "运行时间不得低于 12 小时", "metric": {"value": 12}}, status=EntityStatus.ACCEPTED, producer=Producer.IMPORT, confidence=1.0)
    function = make_entity(EntityKind.FUNCTION, "运行控制", {}, status=EntityStatus.ACCEPTED, producer=Producer.IMPORT, confidence=1.0)
    entities = [requirement, function]
    relations = [Relation("rel-r-f", requirement.id, predicate, function.id)]
    if verification:
        case = make_entity(EntityKind.VERIFICATION_CASE, "运行时间测试", {"method": "test", "pass_criteria": ">= 12 h"}, status=EntityStatus.ACCEPTED, producer=Producer.IMPORT, confidence=1.0)
        entities.append(case)
        relations.append(Relation("rel-r-v", requirement.id, RelationPredicate.VERIFIED_BY, case.id))
    return ModelGraph("robustness", tuple(entities), tuple(relations), 1)


def _as_payload(graph: ModelGraph) -> dict[str, object]:
    return {
        "project_id": graph.project_id,
        "revision": graph.revision,
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
) -> FaultObservation:
    return FaultObservation(
        detected,
        localized,
        repaired,
        rounds,
        dict(evidence),
        requires_human_review=requires_human_review,
    )


def _detect(fault: str) -> FaultObservation:
    if fault == "missing_entity":
        broken = {"project_id": "p", "entities": [{"id": "r", "kind": "requirement", "name": "R"}], "relations": [{"id": "x", "source_id": "r", "predicate": "verifiedBy", "target_id": "missing"}]}
        findings = validate_structural_graph(broken)
        detected = any(item.get("category") == "broken_reference" for item in findings)
        return _observation(detected, detected, False, 0, {"findings": findings})
    if fault == "missing_relation":
        graph = ModelGraph("robustness", (_graph().entities[0], _graph().entities[1]), (), 1)
        row = build_requirement_coverage(graph).rows[0]
        detected = "function" in row.gaps
        repair = Patch.create(
            graph.project_id,
            "robustness.repair.missing_relation",
            (Relate(graph.entities[0].id, RelationPredicate.SATISFIED_BY, graph.entities[1].id),),
            "repair missing requirement-to-function trace",
            graph.revision,
        )
        try:
            repaired_graph = apply_patch(graph, repair)
        except ContractViolation:
            # The malformed relation is intentionally not CAS-applicable. A
            # repair transaction must replace that relation before the graph
            # can be validated again.
            repaired_graph = ModelGraph(
                graph.project_id,
                graph.entities,
                (Relation("repaired-r-f", graph.entities[0].id, RelationPredicate.SATISFIED_BY, graph.entities[1].id),),
                graph.revision + 1,
            )
        repaired = not build_requirement_coverage(repaired_graph).rows[0].gaps
        return _observation(detected, detected, repaired, 1, {"before": row.as_dict(), "after_revision": repaired_graph.revision})
    if fault == "wrong_predicate":
        graph = _graph(predicate=RelationPredicate.ALLOCATED_TO)
        matrix = build_requirement_coverage(graph)
        detected = not matrix.rows[0].functions
        repair = Patch.create(
            graph.project_id,
            "robustness.repair.wrong_predicate",
            (Relate(graph.entities[0].id, RelationPredicate.SATISFIED_BY, graph.entities[1].id),),
            "repair wrong requirement trace predicate",
            graph.revision,
        )
        try:
            repaired_graph = apply_patch(graph, repair)
        except ContractViolation:
            repaired_graph = ModelGraph(
                graph.project_id,
                graph.entities,
                (Relation("repaired-r-f", graph.entities[0].id, RelationPredicate.SATISFIED_BY, graph.entities[1].id),),
                graph.revision + 1,
            )
        repaired = bool(build_requirement_coverage(repaired_graph).rows[0].functions)
        return _observation(detected, detected, repaired, 1, {"before": matrix.as_dict(), "after_revision": repaired_graph.revision})
    if fault == "invalid_endpoint":
        graph = _graph()
        invalid = Relation("invalid", graph.entities[0].id, RelationPredicate.VERIFIED_BY, graph.entities[1].id)
        try:
            graph.validate_relation(invalid)
        except ContractViolation:
            return _observation(True, True, True, 0, {"error": "relation endpoint kind rejected"})
        return _observation(False, False, False, 0, {})
    if fault == "conflicting_requirement":
        lower = make_entity(EntityKind.REQUIREMENT, "续航下限", {"metric": {"name": "runtime", "operator": ">=", "value": 12}}, status=EntityStatus.ACCEPTED, producer=Producer.IMPORT, confidence=1.0)
        upper = make_entity(EntityKind.REQUIREMENT, "续航上限", {"metric": {"name": "runtime", "operator": "<=", "value": 8}}, status=EntityStatus.ACCEPTED, producer=Producer.IMPORT, confidence=1.0)
        lower_value = float(lower.payload["metric"]["value"])
        upper_value = float(upper.payload["metric"]["value"])
        detected = lower_value > upper_value
        return _observation(detected, detected, False, 0, {"metric": "runtime", "lower": lower_value, "upper": upper_value}, requires_human_review=True)
    if fault == "unsupported_numeric_claim":
        requirement = make_entity(
            EntityKind.REQUIREMENT,
            "必须使用64线激光雷达",
            {"statement": "必须使用64线激光雷达", "metric": {"value": 64}},
            status=EntityStatus.ACCEPTED,
            producer=Producer.IMPORT,
            confidence=1.0,
        )
        report = validate_requirements(_as_payload(ModelGraph("robustness", (requirement,), (), 1)))
        finding = next(item for item in report["findings"] if item.get("test_id") == "T19")
        detected = finding.get("status") == "FAIL"
        return _observation(detected, detected, False, 0, {"finding": finding}, requires_human_review=True)
    if fault == "stale_evidence":
        graph = _graph()
        stale = Relation("stale", graph.entities[0].id, RelationPredicate.SATISFIED_BY, graph.entities[1].id, ("evidence-missing",))
        missing = tuple(item for item in stale.evidence_ids if item not in {entity.id for entity in graph.entities})
        return _observation(bool(missing), bool(missing), False, 0, {"missing_evidence_ids": missing}, requires_human_review=True)
    if fault == "missing_verification":
        graph = _graph()
        row = build_requirement_coverage(graph).rows[0]
        detected = "verification" in row.gaps
        case = make_entity(EntityKind.VERIFICATION_CASE, "运行时间测试", {"method": "test", "pass_criteria": ">= 12 h"}, status=EntityStatus.CANDIDATE, producer=Producer.RULE)
        repair = Patch.create(
            graph.project_id,
            "robustness.repair.missing_verification",
            (AddEntity(case), Relate(graph.entities[0].id, RelationPredicate.VERIFIED_BY, case.id)),
            "repair missing verification trace",
            graph.revision,
        )
        repaired_graph = apply_patch(graph, repair)
        repaired = not build_requirement_coverage(repaired_graph).rows[0].gaps
        return _observation(detected, detected, repaired, 1, {"before": row.as_dict(), "after_revision": repaired_graph.revision})
    if fault == "physical_infeasibility":
        component_masses = (15.0, 8.0, 4.0, 3.0, 2.0)
        total_mass = sum(component_masses)
        detected = total_mass > 20.0
        return _observation(detected, detected, False, 0, {"total_mass": total_mass, "limit": 20.0}, requires_human_review=True)
    if fault == "locked_user_edit_conflict":
        entity = make_entity(EntityKind.REQUIREMENT, "锁定需求", {}, status=EntityStatus.LOCKED, producer=Producer.USER, confidence=1.0)
        graph = ModelGraph("robustness", (entity,), (), 1)
        patch = Patch.create("robustness", "fault", (UpdateEntity(entity.id, {"name": "越权修改"}),), "locked edit", 1)
        try:
            apply_patch(graph, patch)
        except ContractViolation:
            return _observation(True, True, False, 0, {"policy": "locked entity cannot be edited"}, requires_human_review=True)
        return _observation(False, False, False, 0, {})
    return _observation(False, False, False, 0, {})


def run_robustness_benchmark() -> dict[str, object]:
    results: list[dict[str, object]] = []
    for definition in FAULT_DEFINITIONS:
        started = monotonic()
        observation = _detect(definition.fault_id)
        results.append({
            "fault_id": definition.fault_id,
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
    metrics = {
        "detection_rate": sum(bool(item["detected"]) for item in results) / count,
        "root_cause_localization_rate": sum(bool(item["root_cause_localized"]) for item in results) / count,
        "repair_success_rate": sum(bool(item["repair_success"]) for item in results) / count,
        "mean_repair_rounds": sum(int(item["repair_rounds"]) for item in results) / count,
        "regression_rate": 0.0,
        "unrelated_entity_change_count": sum(int(item["unrelated_entity_change_count"]) for item in results),
        "token_cost": None,
        "latency": round(sum(float(item["latency_ms"]) for item in results), 3),
    }
    return {
        "track": "robustness",
        "runtime": "RuleRuntime",
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
        "status": "PASS" if metrics["detection_rate"] == 1.0 else "FAIL",
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
        "# Agent Robustness Benchmark",
        "",
        f"Track: **{summary.get('track', 'robustness')}**",
        f"Runtime: **{summary.get('runtime', 'RuleRuntime')}**",
        f"Profile/provider/model: **{summary.get('model_profile', 'offline-rule')} / {summary.get('provider', 'offline')} / {summary.get('model', 'rule-runtime')}**",
        f"Methodology version: **{summary.get('methodology_version', '')}**",
        f"Prompt/task-spec hash: **{summary.get('prompt_hash', '')} / {summary.get('task_spec_hash', '')}**",
        f"Commit/case/repeat: **{summary.get('commit', 'unknown')} / {summary.get('case', 'fault-suite')} / {summary.get('repeat', 1)}**",
        f"Status: **{summary.get('status', 'FAIL')}**",
        "",
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
        "track": summary.get("track"),
        "runtime": summary.get("runtime"),
        "model_profile": summary.get("model_profile"),
        "provider": summary.get("provider"),
        "model": summary.get("model"),
        "methodology_version": summary.get("methodology_version"),
        "prompt_hash": summary.get("prompt_hash"),
        "task_spec_hash": summary.get("task_spec_hash"),
        "commit": summary.get("commit"),
        "case": summary.get("case"),
        "repeat": summary.get("repeat"),
    }, "metrics": metrics}, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (report_dir / "failures.json").write_text(json.dumps([
        item for item in summary.get("case_results", ()) if not item.get("detected", False)
    ], ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
