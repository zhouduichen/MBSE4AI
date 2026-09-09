"""Behavior and interface workbench projection without inferred semantics."""

from __future__ import annotations

from typing import Mapping

from rflp_lite.application.projections.common import entity_card, header, issues_by_entity
from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.model import ModelGraph


_KINDS = (EntityKind.ACTIVITY, EntityKind.FUNCTIONAL_SCENARIO, EntityKind.INTERFACE, EntityKind.STATE)


def build_behavior_view(graph: ModelGraph, issues: tuple[Mapping[str, object], ...] = ()) -> Mapping[str, object]:
    issue_index = issues_by_entity(issues)
    entity_ids = {item.id for item in graph.entities if item.kind in _KINDS}
    records = {kind.value: [entity_card(item, issue_count=len(issue_index.get(item.id, ()))) for item in sorted(graph.entities, key=lambda value: value.id) if item.kind is kind] for kind in _KINDS}
    relations = []
    for relation in sorted(graph.relations, key=lambda item: item.id):
        if relation.source_id in entity_ids and relation.target_id in entity_ids:
            relations.append({"id": relation.id, "source": relation.source_id, "target": relation.target_id, "predicate": relation.predicate.value, "evidence_count": len(relation.evidence_ids)})
    incomplete = []
    for state in records[EntityKind.STATE.value]:
        if not any(item["source"] == state["id"] or item["target"] == state["id"] for item in relations):
            incomplete.append({"entity_id": state["id"], "reason": "state has no recorded transition/interface relation"})
    return {**header(graph).as_dict(), "records": records, "relations": relations, "incomplete": incomplete}
