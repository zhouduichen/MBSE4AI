"""Layered, read-only projection for reviewing the complete ModelGraph."""

from __future__ import annotations

from typing import Mapping

from rflp_lite.application.projections.common import entity_card, header, issues_by_entity
from rflp_lite.domain.entities import EntityKind, EntityStatus
from rflp_lite.domain.model import ModelGraph


_GROUPS: tuple[tuple[str, str, str, tuple[EntityKind, ...]], ...] = (
    (
        "system",
        "系统定义",
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
        "功能",
        "系统行为、功能流与功能场景",
        (EntityKind.FUNCTION, EntityKind.FUNCTIONAL_FLOW, EntityKind.FUNCTIONAL_SCENARIO),
    ),
    (
        "logical",
        "逻辑",
        "逻辑组件、接口与状态",
        (EntityKind.LOGICAL_COMPONENT, EntityKind.INTERFACE, EntityKind.STATE),
    ),
    ("physical", "物理", "物理候选与资源承载", (EntityKind.PHYSICAL_BLOCK,)),
    (
        "assurance",
        "验证与确认",
        "验证、确认、危险源与失效模式",
        (
            EntityKind.VERIFICATION_CASE,
            EntityKind.VALIDATION_CASE,
            EntityKind.HAZARD,
            EntityKind.FAILURE_MODE,
            EntityKind.EVIDENCE,
        ),
    ),
)

_KIND_LABELS = {
    EntityKind.SYSTEM: "系统",
    EntityKind.STAKEHOLDER: "利益相关方",
    EntityKind.CONCERN: "关注点",
    EntityKind.LIFECYCLE_STAGE: "生命周期阶段",
    EntityKind.LIFECYCLE_TRANSITION: "生命周期转移",
    EntityKind.SCENARIO_HYPOTHESIS: "场景假设",
    EntityKind.USE_CASE: "用例",
    EntityKind.OPERATIONAL_SCENARIO: "运行场景",
    EntityKind.ACTIVITY: "活动",
    EntityKind.REQUIREMENT: "需求",
    EntityKind.FUNCTION: "功能",
    EntityKind.FUNCTIONAL_FLOW: "功能流",
    EntityKind.FUNCTIONAL_SCENARIO: "功能场景",
    EntityKind.LOGICAL_COMPONENT: "逻辑组件",
    EntityKind.INTERFACE: "接口",
    EntityKind.STATE: "状态",
    EntityKind.PHYSICAL_BLOCK: "物理块",
    EntityKind.VERIFICATION_CASE: "验证用例",
    EntityKind.VALIDATION_CASE: "确认用例",
    EntityKind.HAZARD: "危险源",
    EntityKind.FAILURE_MODE: "失效模式",
    EntityKind.EVIDENCE: "证据",
}
_STATUS_LABELS = {
    EntityStatus.CANDIDATE: "候选",
    EntityStatus.VALIDATED: "已验证",
    EntityStatus.ACCEPTED: "已接受",
    EntityStatus.LOCKED: "已锁定",
    EntityStatus.REJECTED: "已拒绝",
    EntityStatus.DEPRECATED: "已弃用",
}

_CONTINUABLE_KINDS = frozenset(
    kind
    for _, _, _, kinds in _GROUPS[:4]
    for kind in kinds
) | {EntityKind.REQUIREMENT}


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
                "kind_label": _KIND_LABELS.get(entity.kind, "模型元素"),
                "status_label": _STATUS_LABELS.get(entity.meta.status, entity.meta.status.value),
                "source_count": len(entity.meta.source_ids),
                "evidence_count": len(set(entity.meta.evidence_ids) | relation_evidence.get(entity.id, set())),
                "relation_count": relation_counts.get(entity.id, 0),
                "can_continue": (
                    entity.kind in _CONTINUABLE_KINDS
                    and entity.meta.status in {EntityStatus.ACCEPTED, EntityStatus.LOCKED}
                ),
                "continue_label": (
                    "基于锁定实体继续生成"
                    if entity.meta.status is EntityStatus.LOCKED
                    else "继续生成下游"
                ),
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
