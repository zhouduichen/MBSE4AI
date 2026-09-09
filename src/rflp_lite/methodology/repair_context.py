"""Local, auditable context supplied to a targeted repair strategy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from rflp_lite.domain.entities import Entity
from rflp_lite.domain.model import ModelGraph, Relation


@dataclass(frozen=True, slots=True)
class RepairContext:
    project_id: str
    run_id: str
    issue_id: str
    issue_code: str
    failing_gate: str
    root_entity_ids: tuple[str, ...]
    graph_revision: int
    local_entities: tuple[Entity, ...]
    local_relations: tuple[Relation, ...]
    evidence: tuple[Mapping[str, object], ...]
    expected_trace_rule: str | None = None
    previous_task_id: str | None = None


def build_repair_context(
    project_id: str,
    run_id: str,
    issue_id: str,
    issue: Mapping[str, object],
    graph: ModelGraph,
    *,
    evidence: tuple[Mapping[str, object], ...] = (),
    previous_task_id: str | None = None,
) -> RepairContext:
    """Select roots plus one-hop neighbors while dropping dangling endpoints."""

    index = graph.entity_index
    roots = tuple(sorted({str(item) for item in issue.get("entity_ids", ()) if str(item) in index}))
    local_ids = set(roots)
    for relation in graph.relations:
        if relation.source_id in local_ids or relation.target_id in local_ids:
            if relation.source_id in index and relation.target_id in index:
                local_ids.update((relation.source_id, relation.target_id))
    local_entities = tuple(sorted((index[item] for item in local_ids), key=lambda item: item.id))
    local_relations = tuple(sorted(
        (relation for relation in graph.relations if relation.source_id in local_ids and relation.target_id in local_ids),
        key=lambda item: item.id,
    ))
    return RepairContext(
        project_id,
        run_id,
        issue_id,
        str(issue.get("code", "issue")),
        str(issue.get("failing_gate", issue.get("gate_id", ""))),
        roots,
        graph.revision,
        local_entities,
        local_relations,
        tuple(evidence),
        str(issue.get("expected_trace_rule")) if issue.get("expected_trace_rule") else None,
        previous_task_id,
    )
