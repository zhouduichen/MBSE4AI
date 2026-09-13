"""Layered, read-only projection for reviewing the complete ModelGraph."""

from __future__ import annotations

from typing import Mapping

from rflp_lite.application.projections.common import entity_card, header, issues_by_entity
from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.model import ModelGraph


_GROUPS: tuple[tuple[str, str, str, tuple[EntityKind, ...]], ...] = (
    (
        "system",
        "System Definition",
        "系统定义、利益相关方、生命周期与运行场景",
        (
            EntityKind.SYSTEM,
            EntityKind.STAKEHOLDER,
            EntityKind.CONCERN,
            EntityKind.LIFECYCLE_STAGE,
            EntityKind.LIFECYCLE_TRANSITION,
            EntityKind.SCENARIO_HYPOTHESIS,
            EntityKind.USE_CASE,
            EntityKind.OPERATIONAL_SCENARIO,
            EntityKind.ACTIVITY,
        ),
    ),
    (
        "functional",
        "Functional",
        "系统行为、功能流与功能场景",
        (EntityKind.FUNCTION, EntityKind.FUNCTIONAL_FLOW, EntityKind.FUNCTIONAL_SCENARIO),
    ),
    (
        "logical",
        "Logical",
        "逻辑组件、接口与状态",
        (EntityKind.LOGICAL_COMPONENT, EntityKind.INTERFACE, EntityKind.STATE),
    ),
    ("physical", "Physical", "物理候选与资源承载", (EntityKind.PHYSICAL_BLOCK,)),
    (
        "assurance",
        "V&V",
        "验证、确认、危险源与失效模式",
        (
            EntityKind.VERIFICATION_CASE,
            EntityKind.VALIDATION_CASE,
            EntityKind.HAZARD,
            EntityKind.FAILURE_MODE,
        ),
    ),
)


def build_model_workbench_view(
    graph: ModelGraph,
    issues: tuple[Mapping[str, object], ...] = (),
) -> Mapping[str, object]:
    """Build the user-facing engineering layers without writing to the graph."""

    issue_index = issues_by_entity(issues)
    relation_counts: dict[str, int] = {}
    relation_evidence: dict[str, set[str]] = {}
    for relation in graph.relations:
        for entity_id in (relation.source_id, relation.target_id):
            relation_counts[entity_id] = relation_counts.get(entity_id, 0) + 1
            relation_evidence.setdefault(entity_id, set()).update(relation.evidence_ids)

    groups = []
    grouped_ids: set[str] = set()
    for group_id, title, description, kinds in _GROUPS:
        entities = []
        for entity in sorted(
            (item for item in graph.entities if item.kind in kinds),
            key=lambda item: (item.kind.value, item.id),
        ):
            grouped_ids.add(entity.id)
            card = dict(entity_card(entity, issue_count=len(issue_index.get(entity.id, ()))))
            card.update({
                "source_count": len(entity.meta.source_ids),
                "evidence_count": len(set(entity.meta.evidence_ids) | relation_evidence.get(entity.id, set())),
                "relation_count": relation_counts.get(entity.id, 0),
            })
            entities.append(card)
        groups.append({
            "id": group_id,
            "title": title,
            "description": description,
            "kinds": [kind.value for kind in kinds],
            "count": len(entities),
            "entities": entities,
        })

    grouped_count = len(grouped_ids)
    return {
        **header(graph).as_dict(),
        "groups": groups,
        "metrics": {
            "entity_count": len(graph.entities),
            "relation_count": len(graph.relations),
            "grouped_entity_count": grouped_count,
            "ungrouped_entity_count": len(graph.entities) - grouped_count,
        },
    }
