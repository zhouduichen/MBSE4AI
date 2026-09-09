"""Stakeholder, lifecycle, and scenario coverage checks."""

from __future__ import annotations

from typing import Any, Mapping

from .common import by_kind, entity_text, finding, normalize, ratio, semantic_match


_LIFECYCLE_ALIASES = {
    "design": ("设计", "规划", "concept", "design"),
    "manufacturing": ("制造", "生产", "manufacturing"),
    "deployment": ("部署", "安装", "deployment"),
    "operation": ("运行", "运营", "operation"),
    "maintenance": ("维护", "维修", "运维", "maintenance"),
    "upgrade": ("升级", "更新", "upgrade"),
    "retirement": ("退役", "处置", "更换", "disposal", "retirement"),
}


def _scenario_entities(graph: Mapping[str, object]) -> list[dict[str, Any]]:
    return by_kind(graph, "scenario_hypothesis") + by_kind(graph, "operational_scenario") + by_kind(graph, "functional_scenario")


def _match_any(expected: object, actuals: list[str], aliases: list[list[str]] | tuple[tuple[str, ...], ...] = ()) -> bool:
    return any(semantic_match(expected, actual, aliases) for actual in actuals)


def validate_coverage(case: Mapping[str, object], graph: Mapping[str, object], expectations: Mapping[str, object]) -> dict[str, object]:
    case_id = str(case.get("case_id", ""))
    coverage = expectations.get("coverage", {})
    stakeholder_aliases = [list(value) for value in dict(coverage.get("stakeholder_synonyms", {})).values()]
    actual_stakeholders = [str(item.get("name", "")) for item in by_kind(graph, "stakeholder")]
    expected_stakeholders = [str(item) for item in case.get("stakeholders", ())]
    stakeholder_matches = [
        expected for expected in expected_stakeholders
        if _match_any(expected, actual_stakeholders, stakeholder_aliases)
    ]
    stakeholder_score = ratio(len(stakeholder_matches), len(expected_stakeholders))

    required_lifecycle = list(dict(coverage.get("required_lifecycle", {})).get(case_id, ()))
    actual_lifecycle = [str(item.get("name", "")) for item in by_kind(graph, "lifecycle_stage")]
    lifecycle_matches = [
        expected for expected in required_lifecycle
        if any(semantic_match(expected, actual, (_LIFECYCLE_ALIASES.get(expected, ()),)) for actual in actual_lifecycle)
    ]
    lifecycle_score = ratio(len(lifecycle_matches), len(required_lifecycle))

    actual_scenario_text = [entity_text(item) for item in _scenario_entities(graph)]
    expected_scenarios = [item for item in case.get("scenarios", ()) if isinstance(item, Mapping)]
    scenario_matches = [
        item for item in expected_scenarios
        if _match_any(item.get("name", ""), actual_scenario_text)
        or _match_any(item.get("text", ""), actual_scenario_text)
    ]
    required_phrases = list(dict(coverage.get("required_scenarios", {})).get(case_id, ()))
    phrase_matches = [phrase for phrase in required_phrases if any(normalize(phrase) in normalize(text) for text in actual_scenario_text)]
    scenario_score = ratio(len(scenario_matches), len(expected_scenarios))
    scenario_recall = ratio(len(phrase_matches), len(required_phrases)) if required_phrases else scenario_score

    return {
        "stakeholder_coverage": stakeholder_score,
        "stakeholder_matched": stakeholder_matches,
        "stakeholder_expected": expected_stakeholders,
        "lifecycle_coverage": lifecycle_score,
        "lifecycle_matched": lifecycle_matches,
        "lifecycle_expected": required_lifecycle,
        "scenario_recall": scenario_recall,
        "scenario_matched": [str(item.get("id", item.get("name", ""))) for item in scenario_matches],
        "scenario_expected": [str(item.get("id", item.get("name", ""))) for item in expected_scenarios],
        "scenario_phrase_matched": phrase_matches,
        "scenario_phrase_expected": required_phrases,
        "findings": [
            finding("T1", case_id, "PASS" if stakeholder_score >= 0.85 else "FAIL", severity="P1", category="stakeholder_coverage", expected=">= 85% stakeholder coverage", actual=stakeholder_score, root_cause="" if stakeholder_score >= 0.85 else "semantic stakeholder candidates are missing", recommended_fix="Improve stakeholder analysis to cover operational and lifecycle actors."),
            finding("T2", case_id, "PASS" if lifecycle_score >= 0.90 else "FAIL", severity="P1", category="lifecycle_coverage", expected=">= 90% required lifecycle coverage", actual=lifecycle_score, root_cause="" if lifecycle_score >= 0.90 else "lifecycle stage coverage is incomplete", recommended_fix="Generate explicit lifecycle stages for the case scope."),
            finding("T3", case_id, "PASS" if scenario_recall >= 0.85 else "FAIL", severity="P1", category="scenario_coverage", expected=">= 85% scenario recall", actual=scenario_recall, root_cause="" if scenario_recall >= 0.85 else "required normal/alternative/exception scenarios are missing", recommended_fix="Preserve scenario detail and abnormal branches through the workflow."),
        ],
    }
