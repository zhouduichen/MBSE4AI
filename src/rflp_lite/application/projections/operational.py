"""Operational analysis projection using only recorded graph facts."""

from __future__ import annotations

from typing import Mapping

from rflp_lite.application.projections.common import entity_card, header, issues_by_entity, related_cards
from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.model import ModelGraph


_KINDS = (EntityKind.STAKEHOLDER, EntityKind.LIFECYCLE_STAGE, EntityKind.LIFECYCLE_TRANSITION, EntityKind.USE_CASE, EntityKind.OPERATIONAL_SCENARIO, EntityKind.ACTIVITY)


def build_operational_view(graph: ModelGraph, issues: tuple[Mapping[str, object], ...] = ()) -> Mapping[str, object]:
    issue_index = issues_by_entity(issues)
    sections = []
    for kind in _KINDS:
        entities = tuple(sorted((item for item in graph.entities if item.kind is kind), key=lambda item: item.id))
        sections.append({"kind": kind.value, "label": kind.value.replace("_", " ").title(), "records": [entity_card(item, issue_count=len(issue_index.get(item.id, ()))) for item in entities]})
    scenarios = []
    for entity in sorted((item for item in graph.entities if item.kind is EntityKind.OPERATIONAL_SCENARIO), key=lambda item: item.id):
        scenarios.append({
            **entity_card(entity, issue_count=len(issue_index.get(entity.id, ()))),
            "actors": list(related_cards(graph, entity.id, outgoing=False, issues=issue_index)),
            "linked_requirements": [card for card in related_cards(graph, entity.id, outgoing=False, issues=issue_index) if card["kind"] == EntityKind.REQUIREMENT.value],
            "steps": entity.payload.get("steps", []),
            "exchanges": entity.payload.get("exchanges", []),
            "preconditions": entity.payload.get("preconditions", []),
            "postconditions": entity.payload.get("postconditions", []),
        })
    return {**header(graph).as_dict(), "sections": sections, "scenarios": scenarios}
