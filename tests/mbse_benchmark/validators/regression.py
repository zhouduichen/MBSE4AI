"""Three-run semantic and structural stability checks."""

from __future__ import annotations

from typing import Mapping

from .common import finding, ratio


def _signature(result: Mapping[str, object]) -> dict[str, object]:
    graph = result.get("graph", {})
    entities = graph.get("entities", ()) if isinstance(graph, Mapping) else ()
    relations = graph.get("relations", ()) if isinstance(graph, Mapping) else ()
    return {
        "entities": sorted((str(item.get("kind", "")), str(item.get("name", ""))) for item in entities if isinstance(item, Mapping)),
        "relations": sorted((str(item.get("source_id", "")), str(item.get("predicate", "")), str(item.get("target_id", ""))) for item in relations if isinstance(item, Mapping)),
        "execution_status": str(result.get("execution", {}).get("status", "")) if isinstance(result.get("execution"), Mapping) else "",
    }


def validate_regression(results: list[Mapping[str, object]], case_id: str) -> dict[str, object]:
    if len(results) < 3:
        return {
            "regression_stability": 0.0,
            "findings": [finding("T20", case_id, "BLOCKED", severity="P1", category="regression", expected="3 repeats", actual=len(results), root_cause="fewer than three runs were available", recommended_fix="Run the case three times in isolated workspaces.")],
        }
    signatures = [_signature(item) for item in results]
    baseline = signatures[0]
    stable = sum(1 for item in signatures[1:] if item == baseline)
    status_stable = sum(1 for item in signatures if item["execution_status"] == "completed")
    score = ratio(stable + 1, len(signatures)) * ratio(status_stable, len(signatures))
    return {
        "regression_stability": round(score, 6),
        "repeat_signatures": signatures,
        "findings": [finding("T20", case_id, "PASS" if score >= 0.85 else "FAIL", severity="P1", category="regression", expected=">= 85% semantic/structural stability", actual=score, root_cause="repeated runs differ in graph structure or execution status" if score < 0.85 else "", recommended_fix="Make generation and model patch identity deterministic, or record acceptable semantic equivalence explicitly.")],
    }
