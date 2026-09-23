"""Architecture consistency and orphan element checks."""

from __future__ import annotations

from typing import Any, Mapping

from .common import by_id, by_kind, edge_map, finding, payload, ratio


_ROOT_KINDS = {"system", "stakeholder", "lifecycle_stage", "scenario_hypothesis"}


def validate_architecture(graph: Mapping[str, object], case: Mapping[str, object]) -> dict[str, object]:
    index = by_id(graph)
    outgoing, incoming = edge_map(graph)
    orphan: list[str] = []
    orphan_by_kind: dict[str, list[str]] = {}
    for entity in graph.get("entities", ()):
        if not isinstance(entity, Mapping):
            continue
        entity_id = str(entity.get("id", ""))
        kind = str(entity.get("kind", ""))
        if not entity_id or kind in _ROOT_KINDS:
            continue
        has_source_metadata = bool(entity.get("source_ids")) or bool(payload(entity).get("fixture_id"))
        if not outgoing.get(entity_id) and not incoming.get(entity_id) and not has_source_metadata:
            orphan.append(entity_id)
            orphan_by_kind.setdefault(kind, []).append(entity_id)
    total = len([item for item in graph.get("entities", ()) if isinstance(item, Mapping)])
    orphan_rate = ratio(len(orphan), total)
    architecture_kinds = {str(item.get("kind", "")) for item in graph.get("entities", ()) if isinstance(item, Mapping)}
    implemented = {"function", "logical_component", "physical_block"} <= architecture_kinds
    def status(value: float | None, threshold: float) -> str:
        if value is None:
            return "N/A"
        return "PASS" if value <= threshold else "FAIL"

    return {
        "orphan_element_rate": orphan_rate,
        "orphan_ids": orphan,
        "orphan_by_kind": orphan_by_kind,
        "architecture_layers_present": sorted(architecture_kinds & {"function", "logical_component", "physical_block"}),
        "findings": [
            finding("T16", str(case.get("case_id", graph.get("project_id", ""))), status(orphan_rate, 0.05), severity="P1", category="orphan_detection", expected="orphan element rate <= 5%", actual=orphan_rate, related_elements=orphan, root_cause="model elements have no trace or source" if orphan else "", recommended_fix="Require every generated node to carry a source relation or lifecycle rationale."),
            finding("T9/T11", str(case.get("case_id", graph.get("project_id", ""))), "PASS" if implemented else "NOT_IMPLEMENTED", severity="P1", category="architecture_layers", expected="Function, Logical, and Physical layers present", actual=sorted(architecture_kinds & {"function", "logical_component", "physical_block"}), root_cause="one or more RFLP layers are absent" if not implemented else "", recommended_fix="Implement the missing architecture stage before claiming RFLP coverage."),
        ],
    }
