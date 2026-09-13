"""Cross-stage numeric/logical feasibility and iteration checks."""

from __future__ import annotations

import re
from typing import Any, Mapping

from .common import by_kind, finding, has_failure_signal, normalize, numeric_values, payload, ratio, text_of


def _comparison_satisfied(actual: float, operator: str, limit: float) -> bool:
    if operator in {"<=", "<"}:
        return actual <= limit if operator == "<=" else actual < limit
    if operator in {">=", ">"}:
        return actual >= limit if operator == ">=" else actual > limit
    return actual == limit


def _case05_conflicts(case: Mapping[str, object], graph: Mapping[str, object], raw_result: Mapping[str, object]) -> list[dict[str, object]]:
    components = [item for item in case.get("physical_design", ()) if isinstance(item, Mapping)]
    total_mass = sum(float(item.get("mass", 0) or 0) for item in components)
    power_budget = case.get("power_budget", {})
    average_power = float(power_budget.get("average_power", 0) or 0) if isinstance(power_budget, Mapping) else 0.0
    battery_energy = sum(float(item.get("energy", 0) or 0) for item in components)
    runtime_hours = battery_energy / average_power if average_power else 0.0
    requirements = {str(item.get("id", "")): item for item in case.get("requirements", ()) if isinstance(item, Mapping)}
    expected: list[dict[str, object]] = []
    weight = requirements.get("REQ-WEIGHT", {}).get("metric", {})
    if isinstance(weight, Mapping) and total_mass > float(weight.get("value", 0) or 0):
        expected.append({"conflict_id": "weight-conflict", "actual_value": total_mass, "limit": weight.get("value"), "unit": "kg"})
    runtime = requirements.get("REQ-RUNTIME", {}).get("metric", {})
    if isinstance(runtime, Mapping) and runtime_hours < float(runtime.get("value", 0) or 0):
        expected.append({"conflict_id": "runtime-conflict", "actual_value": runtime_hours, "limit": runtime.get("value"), "unit": "h"})
    return expected


def validate_consistency(case: Mapping[str, object], graph: Mapping[str, object], raw_result: Mapping[str, object], expectations: Mapping[str, object]) -> dict[str, object]:
    case_id = str(case.get("case_id", ""))
    expected_conflicts = _case05_conflicts(case, graph, raw_result) if case_id == "CASE-05" else []
    conflict_signals = []
    for conflict in expected_conflicts:
        conflict_id = str(conflict["conflict_id"])
        signal = has_failure_signal(raw_result, (conflict_id, "conflict", "violate", "infeasible", "不满足", "冲突", "不可行"))
        conflict_signals.append({**conflict, "detected": signal})
    detected = sum(1 for item in conflict_signals if item["detected"])
    conflict_score = ratio(detected, len(conflict_signals))
    false_satisfaction = bool(expected_conflicts) and not has_failure_signal(raw_result, ("conflict", "violate", "infeasible", "不满足", "冲突", "不可行")) and bool(by_kind(graph, "physical_block"))
    run_summary = raw_result.get("run_summary", {})
    raw_summary = raw_result.get("run_summary", {})
    summary_evidence = {}
    if isinstance(raw_summary, Mapping):
        summary_evidence = {
            "status": raw_summary.get("status"),
            "diagnostics": raw_summary.get("diagnostics", ()),
            "phase_results": raw_summary.get("phase_results", ()),
            "gate_results": raw_summary.get("gate_results", ()),
            "closure_status": raw_summary.get("closure", {}).get("status")
            if isinstance(raw_summary.get("closure"), Mapping)
            else "",
        }
    lifecycle_evidence = normalize({
        "issues": raw_result.get("issues", []),
        "run_summary": summary_evidence,
        "audit": raw_result.get("audit", {}),
    })
    iteration_signal = any(
        normalize(term) in lifecycle_evidence
        for term in ("repair", "rollback", "rerun", "iteration", "修复", "回退", "重跑", "迭代")
    )
    impact_terms = {"scenario": False, "function": False, "battery": False, "power": False, "physical": False, "verification": False}
    haystack = normalize(raw_result)
    for term in impact_terms:
        impact_terms[term] = normalize(term) in haystack
    return {
        "expected_conflicts": expected_conflicts,
        "conflict_signals": conflict_signals,
        "known_conflict_detection": conflict_score,
        "false_satisfaction_signal": false_satisfaction,
        "iteration_signal": iteration_signal,
        "change_impact_terms": impact_terms,
        "findings": [
            finding("T10", case_id, "PASS" if conflict_score == 1.0 else "FAIL" if expected_conflicts else "NOT_IMPLEMENTED", severity="P0", category="architecture_requirement_conflict", expected="detect CASE-05 weight and runtime conflicts", actual=conflict_signals, related_elements=["REQ-WEIGHT", "REQ-RUNTIME", "PHY-BATTERY", "PHY-CHASSIS", "PHY-MOTOR", "PHY-SENSOR", "PHY-COMPUTE"] if expected_conflicts else (), root_cause="physical design conflict is arithmetically present but no model issue/diagnostic indicates it" if expected_conflicts and conflict_score < 1.0 else "", recommended_fix="Add generic mass/energy/power feasibility checks to Assurance and prevent SATISFIED claims."),
            finding("T17", case_id, "PASS" if iteration_signal else "FAIL", severity="P0", category="iteration", expected="verification failure leads to diagnosis, modification, and re-verification", actual=iteration_signal, root_cause="no failure feedback or targeted iteration evidence is recorded" if not iteration_signal else "", recommended_fix="Persist failure-to-requirement impact and rerun the smallest affected stage."),
            finding("T18", case_id, "PASS" if all(impact_terms.values()) else "NOT_IMPLEMENTED", severity="P1", category="change_impact", expected="requirement change identifies affected design and verification elements", actual=impact_terms, root_cause="change impact analysis is not represented" if not all(impact_terms.values()) else "", recommended_fix="Add versioned impact traversal from requirement to scenario, function, power/physical design, and verification."),
            finding("T9", case_id, "FAIL" if false_satisfaction else "PASS", severity="P0", category="false_satisfied_architecture", expected="violated physical architecture must not be reported SATISFIED", actual=false_satisfaction, root_cause="physical blocks exist without a corresponding violation signal" if false_satisfaction else "", recommended_fix="Gate closure on numeric feasibility findings."),
        ],
    }
