"""Behavior and interface workbench projection without inferred semantics."""

from __future__ import annotations

import re
from typing import Mapping

from rflp_lite.application.projections.common import entity_card, header, issues_by_entity
from rflp_lite.domain.entities import Entity, EntityKind
from rflp_lite.domain.model import ModelGraph
from rflp_lite.domain.relations import RelationPredicate


_KINDS = (
    EntityKind.USE_CASE,
    EntityKind.OPERATIONAL_SCENARIO,
    EntityKind.ACTIVITY,
    EntityKind.FUNCTIONAL_SCENARIO,
    EntityKind.INTERFACE,
    EntityKind.STATE,
)
_RELATION_KINDS = frozenset((*_KINDS, EntityKind.REQUIREMENT))


def _requirement_ids_for_entity(graph: ModelGraph, entity: Entity) -> list[str]:
    """Read requirement links from graph relations, with a legacy payload fallback."""

    index = graph.entity_index
    explicit = sorted(
        relation.source_id
        for relation in graph.relations
        if relation.target_id == entity.id
        and relation.predicate is RelationPredicate.DERIVED_FROM
        and index.get(relation.source_id) is not None
        and index[relation.source_id].kind is EntityKind.REQUIREMENT
    )
    raw_payload_ids = entity.payload.get("requirement_ids", ())
    payload_ids = (raw_payload_ids,) if isinstance(raw_payload_ids, str) else raw_payload_ids
    payload_requirement_ids = [
        str(value)
        for value in (payload_ids or ())
        if str(value) in index and index[str(value)].kind is EntityKind.REQUIREMENT
    ]
    return list(dict.fromkeys((*explicit, *payload_requirement_ids)))


def _mermaid_text(value: object, default: str = "") -> str:
    """Keep user/model text on one Mermaid line without allowing syntax injection."""

    text = str(value or default).replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).replace('"', "'").strip() or default


def _flowchart_text(value: object, default: str = "") -> str:
    """Keep labels from changing Mermaid flowchart structure."""

    return (
        _mermaid_text(value, default)
        .replace("[", "(")
        .replace("]", ")")
        .replace("{", "(")
        .replace("}", ")")
        .replace(";", ",")
    )


def _scenario_steps(graph: ModelGraph, scenario: Entity) -> tuple[tuple[Entity, ...], list[Mapping[str, object]]]:
    """Return graph-backed activity entities and their normalized scenario steps."""

    activity_items = tuple(sorted(
        (
            item
            for item in graph.entities
            if item.kind is EntityKind.ACTIVITY
            and str(item.payload.get("scenario_id", "")) == scenario.id
        ),
        key=lambda item: (int(item.payload.get("order", 0) or 0), item.id),
    ))
    raw_steps = activity_items or tuple(scenario.payload.get("steps", ()) or ())
    steps: list[Mapping[str, object]] = []
    for index, raw_step in enumerate(raw_steps, start=1):
        if hasattr(raw_step, "payload"):
            payload = raw_step.payload
        elif isinstance(raw_step, Mapping):
            payload = raw_step
        elif isinstance(raw_step, str):
            payload = {"action": raw_step}
        else:
            payload = {}
        if not isinstance(payload, Mapping):
            continue
        activity_id = raw_step.id if hasattr(raw_step, "id") else ""
        steps.append({
            "order": int(payload.get("order", index) or index),
            "activity_id": activity_id,
            "actor_id": str(payload.get("actor_id", "") or ""),
            "action": str(payload.get("action", "") or "").strip() or "活动",
            "guard": str(payload.get("guard", "") or "").strip(),
        })
    steps.sort(key=lambda item: (int(item["order"]), str(item["activity_id"])))
    return activity_items, steps


def _scenario_requirement_ids(
    graph: ModelGraph,
    scenario: Entity,
    activity_items: tuple[Entity, ...],
) -> list[str]:
    """Combine scenario and activity requirement links for diagram traceability."""

    requirement_ids = set(_requirement_ids_for_entity(graph, scenario))
    for activity in activity_items:
        requirement_ids.update(_requirement_ids_for_entity(graph, activity))
    return sorted(requirement_ids)


def _sequence_diagrams(graph: ModelGraph) -> list[Mapping[str, object]]:
    """Project recorded scenario/activity data into an editable sequence view.

    This is deliberately a projection rather than a new graph entity: the scenario
    and activities remain the source of truth, so edits made through the workbench
    are reflected on the next read without requiring a diagram synchronization job.
    """

    entities = graph.entity_index
    systems = sorted(
        (item for item in graph.entities if item.kind is EntityKind.SYSTEM),
        key=lambda item: item.id,
    )
    system = systems[0] if systems else None
    system_id = system.id if system is not None else "system"
    system_name = system.meta.name if system is not None else "系统"
    diagrams: list[Mapping[str, object]] = []

    for scenario in sorted(
        (item for item in graph.entities if item.kind is EntityKind.OPERATIONAL_SCENARIO),
        key=lambda item: item.id,
    ):
        activity_items, steps = _scenario_steps(graph, scenario)

        actor_ids: list[str] = []
        for raw_id in list(scenario.payload.get("actor_ids", ()) or ()) + [
            str(step["actor_id"]) for step in steps if step["actor_id"]
        ]:
            actor_id = str(raw_id)
            if actor_id and actor_id not in actor_ids and actor_id != system_id:
                actor_ids.append(actor_id)
        participants: list[Mapping[str, object]] = [
            {"id": system_id, "alias": "system", "name": system_name, "role": "system"}
        ]
        for position, actor_id in enumerate(actor_ids, start=1):
            actor = entities.get(actor_id)
            participants.append({
                "id": actor_id,
                "alias": f"actor{position}",
                "name": actor.meta.name if actor is not None else actor_id,
                "role": actor.kind.value if actor is not None else "actor",
            })
        participant_aliases = {str(item["id"]): str(item["alias"]) for item in participants}

        messages: list[Mapping[str, object]] = []
        mermaid_lines = ["sequenceDiagram"]
        for participant in participants:
            mermaid_lines.append(
                f"  participant {participant['alias']} as {_mermaid_text(participant['name'], '参与者')}"
            )
        for step in steps:
            actor_id = str(step["actor_id"] or system_id)
            source_id = actor_id if actor_id in participant_aliases else system_id
            target_id = system_id
            source_alias = participant_aliases[source_id]
            target_alias = participant_aliases[target_id]
            message = {
                "order": step["order"],
                "activity_id": step["activity_id"],
                "source_id": source_id,
                "target_id": target_id,
                "source_alias": source_alias,
                "target_alias": target_alias,
                "action": step["action"],
                "guard": step["guard"],
            }
            messages.append(message)
            mermaid_lines.append(
                f"  {source_alias}->>{target_alias}: {_mermaid_text(step['action'], '活动')}"
            )
            if step["guard"]:
                mermaid_lines.append(
                    f"  Note over {target_alias}: 守卫：{_mermaid_text(step['guard'])}"
                )

        branches: list[Mapping[str, str]] = []
        for branch in scenario.payload.get("branches", ()) or ():
            if isinstance(branch, Mapping):
                condition = str(branch.get("condition", "")).strip()
                action = str(branch.get("action", "")).strip()
            elif isinstance(branch, str):
                condition, action = branch.strip(), ""
            else:
                continue
            if condition or action:
                branches.append({"condition": condition, "action": action})
        if branches:
            for index, branch in enumerate(branches):
                if index == 0:
                    mermaid_lines.append(f"  alt {_mermaid_text(branch['condition'], '分支')}")
                else:
                    mermaid_lines.append(f"  else {_mermaid_text(branch['condition'], '分支')}")
                mermaid_lines.append(
                    f"    system->>system: {_mermaid_text(branch['action'], '执行分支')}"
                )
            mermaid_lines.append("  end")

        diagrams.append({
            "scenario_id": scenario.id,
            "scenario_name": scenario.meta.name,
            "requirement_ids": _scenario_requirement_ids(graph, scenario, activity_items),
            "diagram_kind": "sequence",
            "format": "mermaid",
            "participants": participants,
            "messages": messages,
            "branches": branches,
            "mermaid": "\n".join(mermaid_lines),
            "editable_entity_ids": [scenario.id, *(item.id for item in activity_items)],
        })
    return diagrams


def _activity_diagrams(graph: ModelGraph) -> list[Mapping[str, object]]:
    """Project operational activities into editable Mermaid activity diagrams."""

    diagrams: list[Mapping[str, object]] = []
    scenarios = sorted(
        (item for item in graph.entities if item.kind is EntityKind.OPERATIONAL_SCENARIO),
        key=lambda item: item.id,
    )
    for scenario in scenarios:
        activity_items, steps = _scenario_steps(graph, scenario)
        nodes: list[Mapping[str, object]] = []
        transitions: list[Mapping[str, object]] = []
        lines = ["flowchart TD", "  start((开始))"]
        previous_id = "start"
        finish_id = "finish"
        for index, step in enumerate(steps, start=1):
            node_id = str(step["activity_id"]) or f"activity_{index}"
            node_id = re.sub(r"[^A-Za-z0-9_]", "_", node_id) or f"activity_{index}"
            label = _flowchart_text(step["action"], "活动")
            if step["guard"]:
                label += f"<br/>守卫：{_flowchart_text(step['guard'])}"
            lines.append(f'  {node_id}["{label}"]')
            lines.append(f"  {previous_id} --> {node_id}")
            transitions.append({"source_id": previous_id, "target_id": node_id, "guard": step["guard"]})
            nodes.append({
                "id": node_id,
                "entity_id": str(step["activity_id"]),
                "order": step["order"],
                "action": step["action"],
                "guard": step["guard"],
            })
            previous_id = node_id

        branches: list[Mapping[str, object]] = []
        for index, branch in enumerate(scenario.payload.get("branches", ()) or (), start=1):
            if isinstance(branch, Mapping):
                condition = str(branch.get("condition", "")).strip()
                action = str(branch.get("action", "")).strip()
            elif isinstance(branch, str):
                condition, action = branch.strip(), ""
            else:
                continue
            if not condition and not action:
                continue
            decision_id = f"decision_{index}"
            action_id = f"branch_{index}"
            lines.append(f'  {decision_id}{{"{_flowchart_text(condition, "分支")}"}}')
            lines.append(f"  {previous_id} --> {decision_id}")
            lines.append(f'  {decision_id} -->|是| {action_id}["{_flowchart_text(action, "执行分支")}"]')
            lines.append(f"  {decision_id} -->|否| {finish_id}")
            transitions.extend((
                {"source_id": previous_id, "target_id": decision_id, "guard": ""},
                {"source_id": decision_id, "target_id": action_id, "guard": condition},
                {"source_id": decision_id, "target_id": finish_id, "guard": f"非：{condition}"},
            ))
            branches.append({"id": decision_id, "condition": condition, "action": action})
        if not branches:
            lines.append(f"  {previous_id} --> {finish_id}")
        lines.append(f"  {finish_id}((结束))")
        diagrams.append({
            "scenario_id": scenario.id,
            "scenario_name": scenario.meta.name,
            "requirement_ids": _scenario_requirement_ids(graph, scenario, activity_items),
            "diagram_kind": "activity",
            "format": "mermaid",
            "nodes": nodes,
            "transitions": transitions,
            "branches": branches,
            "mermaid": "\n".join(lines),
            "editable_entity_ids": [scenario.id, *(item.id for item in activity_items)],
        })
    return diagrams


def build_behavior_view(graph: ModelGraph, issues: tuple[Mapping[str, object], ...] = ()) -> Mapping[str, object]:
    issue_index = issues_by_entity(issues)
    entity_ids = {item.id for item in graph.entities if item.kind in _RELATION_KINDS}
    records = {kind.value: [entity_card(item, issue_count=len(issue_index.get(item.id, ()))) for item in sorted(graph.entities, key=lambda value: value.id) if item.kind is kind] for kind in _KINDS}
    relations = []
    for relation in sorted(graph.relations, key=lambda item: item.id):
        if relation.source_id in entity_ids and relation.target_id in entity_ids:
            relations.append({"id": relation.id, "source": relation.source_id, "target": relation.target_id, "predicate": relation.predicate.value, "evidence_count": len(relation.evidence_ids)})
    scenarios = []
    for entity in sorted(
        (item for item in graph.entities if item.kind is EntityKind.OPERATIONAL_SCENARIO),
        key=lambda item: item.id,
    ):
        scenarios.append({
            **entity_card(entity, issue_count=len(issue_index.get(entity.id, ()))),
            "description": entity.payload.get("description", ""),
            "actor_ids": entity.payload.get("actor_ids", []),
            "steps": entity.payload.get("steps", []),
            "branches": entity.payload.get("branches", []),
            "requirement_ids": _requirement_ids_for_entity(graph, entity),
        })
    use_cases = []
    for entity in sorted(
        (item for item in graph.entities if item.kind is EntityKind.USE_CASE),
        key=lambda item: item.id,
    ):
        use_cases.append({
            **entity_card(entity, issue_count=len(issue_index.get(entity.id, ()))),
            "goal": entity.payload.get("goal", ""),
            "primary_actor_ids": entity.payload.get("primary_actor_ids", []),
            "scenario_ids": entity.payload.get("scenario_ids", []),
            "requirement_ids": _requirement_ids_for_entity(graph, entity),
        })
    incomplete = []
    for state in records[EntityKind.STATE.value]:
        if not any(item["source"] == state["id"] or item["target"] == state["id"] for item in relations):
            incomplete.append({"entity_id": state["id"], "reason": "state has no recorded transition/interface relation"})
    return {
        **header(graph).as_dict(),
        "records": records,
        "relations": relations,
        "scenarios": scenarios,
        "sequence_diagrams": _sequence_diagrams(graph),
        "activity_diagrams": _activity_diagrams(graph),
        "use_cases": use_cases,
        "incomplete": incomplete,
    }
