"""Deterministic TaskSpec completion-condition evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from rflp_lite.domain.entities import EntityKind, EntityStatus
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.contracts import TaskExecutionResponse, TaskSpec
from rflp_lite.methodology.coverage_matrix import build_requirement_coverage


@dataclass(frozen=True, slots=True)
class CompletionResult:
    passed: bool
    checks: tuple[Mapping[str, object], ...] = ()
    issue_codes: tuple[str, ...] = ()


def evaluate_completion(task: TaskSpec, graph: ModelGraph, response: TaskExecutionResponse | None = None) -> CompletionResult:
    condition = task.completion_condition
    active = tuple(entity for entity in graph.entities if entity.meta.status is not EntityStatus.DEPRECATED)
    output_entities = tuple(entity for entity in active if entity.kind in condition.required_output_kinds)
    checks: list[Mapping[str, object]] = []
    issues: list[str] = []
    if condition.minimum_entities:
        count_ok = len(output_entities) >= condition.minimum_entities
        checks.append({"id": "minimum_entities", "passed": count_ok, "actual": len(output_entities), "expected": condition.minimum_entities})
        if not count_ok:
            issues.append("completion_minimum_entities")
    elif response is not None and response.patch is not None and condition.required_output_kinds:
        produced_kinds = {operation.entity.kind for operation in response.patch.operations if hasattr(operation, "entity")}
        kinds_ok = condition.required_output_kinds <= produced_kinds or bool(output_entities)
        checks.append({"id": "required_output_kinds", "passed": kinds_ok, "actual": sorted(kind.value for kind in produced_kinds), "expected": sorted(kind.value for kind in condition.required_output_kinds)})
        if not kinds_ok:
            issues.append("completion_output_kinds")
    if condition.require_accepted:
        accepted_ok = bool(output_entities) and all(entity.meta.status is EntityStatus.ACCEPTED for entity in output_entities)
        checks.append({"id": "require_accepted", "passed": accepted_ok})
        if not accepted_ok:
            issues.append("completion_requires_accepted")
    matrix = build_requirement_coverage(graph)
    for rule in condition.required_trace_rules:
        passed = _trace_rule_passed(rule, matrix.metrics)
        checks.append({"id": rule, "passed": passed})
        if not passed:
            issues.append(f"completion_trace:{rule}")
    return CompletionResult(not issues, tuple(checks), tuple(issues))


def _trace_rule_passed(rule: str, metrics: Mapping[str, object]) -> bool:
    aliases = {
        "requirement_to_function": "r_to_f_coverage",
        "r_to_f": "r_to_f_coverage",
        "r_to_f_to_l": "r_to_f_to_l_coverage",
        "r_to_f_to_l_to_p": "r_to_f_to_l_to_p_coverage",
        "requirement_to_verification": "r_to_v_coverage",
        "r_to_v": "r_to_v_coverage",
    }
    metric = aliases.get(rule, rule)
    value = metrics.get(metric)
    return isinstance(value, (int, float)) and float(value) >= 1.0
