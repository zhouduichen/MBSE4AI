"""Requirements workbench projections."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping

from rflp_lite.application.projections.common import (
    entity_card, header, issues_by_entity, related_cards, requirement_trace_status,
    statement,
)
from rflp_lite.domain.entities import Entity, EntityKind
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.coverage_matrix import build_requirement_coverage


@dataclass(frozen=True, slots=True)
class RequirementRowView:
    id: str
    name: str
    statement: str
    level: str
    type: str
    status: str
    producer: str
    confidence: float | None
    source_count: int
    evidence_count: int
    verification_count: int
    function_count: int
    logical_count: int
    physical_count: int
    trace_status: str
    issue_count: int
    locked: bool

    def as_dict(self) -> Mapping[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RequirementDetailView:
    entity: Mapping[str, object]
    statement: str
    payload: Mapping[str, object]
    sources: tuple[Mapping[str, object], ...]
    evidence: tuple[Mapping[str, object], ...]
    upstream: tuple[Mapping[str, object], ...]
    downstream: tuple[Mapping[str, object], ...]
    functions: tuple[Mapping[str, object], ...]
    logical_components: tuple[Mapping[str, object], ...]
    physical_blocks: tuple[Mapping[str, object], ...]
    verification_cases: tuple[Mapping[str, object], ...]
    hazards: tuple[Mapping[str, object], ...]
    issues: tuple[Mapping[str, object], ...]
    trace_path: tuple[str, ...]
    revision: int

    def as_dict(self) -> Mapping[str, object]:
        return asdict(self)


def _row(graph: ModelGraph, entity: Entity, issues: Mapping[str, tuple[Mapping[str, object], ...]]) -> RequirementRowView:
    status, _gaps, trace = requirement_trace_status(graph, entity)
    relation_evidence = {
        evidence_id
        for relation in graph.relations
        if relation.source_id == entity.id or relation.target_id == entity.id
        for evidence_id in relation.evidence_ids
    }
    return RequirementRowView(
        entity.id,
        entity.meta.name,
        statement(entity),
        str(entity.payload.get("level", entity.payload.get("requirement_level", "system"))),
        str(entity.payload.get("type", entity.payload.get("requirement_type", "functional"))),
        entity.meta.status.value,
        entity.meta.producer.value,
        entity.meta.confidence,
        len(entity.meta.source_ids),
        len(set(entity.meta.evidence_ids) | relation_evidence),
        len(trace["verification"]),
        len(trace["functions"]),
        len(trace["logical"]),
        len(trace["physical"]),
        status,
        len(issues.get(entity.id, ())),
        entity.meta.status.value == "locked",
    )


def build_requirements_view(graph: ModelGraph, issues: tuple[Mapping[str, object], ...] = ()) -> Mapping[str, object]:
    issue_index = issues_by_entity(issues)
    requirements = tuple(sorted((entity for entity in graph.entities if entity.kind is EntityKind.REQUIREMENT), key=lambda item: item.id))
    rows = tuple(_row(graph, entity, issue_index) for entity in requirements)
    accepted_coverage = build_requirement_coverage(graph)
    return {
        **header(graph).as_dict(),
        "rows": [row.as_dict() for row in rows],
        "filters": {"statuses": sorted({row.status for row in rows}), "levels": sorted({row.level for row in rows}), "types": sorted({row.type for row in rows}), "producers": sorted({row.producer for row in rows})},
        "metrics": {"requirement_count": len(rows), "candidate_count": sum(row.status == "candidate" for row in rows), "accepted_count": sum(row.status == "accepted" for row in rows), "locked_count": sum(row.locked for row in rows), "issue_count": sum(row.issue_count for row in rows)},
        "gate_coverage": accepted_coverage.as_dict(),
    }


def build_requirement_detail(graph: ModelGraph, entity_id: str, *, issues: tuple[Mapping[str, object], ...] = (), evidence: tuple[Mapping[str, object], ...] = ()) -> Mapping[str, object] | None:
    entity = graph.entity_index.get(entity_id)
    if entity is None or entity.kind is not EntityKind.REQUIREMENT:
        return None
    issue_index = issues_by_entity(issues)
    _status, _gaps, trace_values = requirement_trace_status(graph, entity)
    target_ids = {item for values in trace_values.values() for item in values}
    valid_relation_evidence = {
        evidence_id for relation in graph.relations if relation.source_id == entity.id or relation.target_id == entity.id for evidence_id in relation.evidence_ids
    }
    evidence_by_id = {str(item.get("id")): item for item in evidence}
    evidence_views = []
    for evidence_id in sorted(set(entity.meta.evidence_ids) | valid_relation_evidence):
        evidence_views.append(evidence_by_id.get(evidence_id, {"id": evidence_id, "status": "unresolved"}))
    sources = tuple({"id": source_id, "reference": source_id} for source_id in sorted(entity.meta.source_ids))
    cards = tuple(entity_card(graph.entity_index[item], issue_count=len(issue_index.get(item, ()))) for item in sorted(target_ids) if item in graph.entity_index)
    functions = tuple(card for card in cards if card["kind"] == EntityKind.FUNCTION.value)
    logical = tuple(card for card in cards if card["kind"] == EntityKind.LOGICAL_COMPONENT.value)
    physical = tuple(card for card in cards if card["kind"] == EntityKind.PHYSICAL_BLOCK.value)
    verification = tuple(card for card in cards if card["kind"] == EntityKind.VERIFICATION_CASE.value)
    hazards = tuple(entity_card(item, issue_count=len(issue_index.get(item.id, ()))) for item in graph.entities if item.kind in {EntityKind.HAZARD, EntityKind.FAILURE_MODE} and any(relation.source_id == item.id and relation.target_id == entity.id and relation.predicate.value == "mitigatedBy" for relation in graph.relations))
    detail = RequirementDetailView(
        entity.as_dict(), statement(entity), dict(entity.payload), sources, tuple(evidence_views),
        related_cards(graph, entity.id, outgoing=False, issues=issue_index),
        related_cards(graph, entity.id, outgoing=True, issues=issue_index),
        functions, logical, physical, verification, hazards,
        tuple(issue_index.get(entity.id, ())),
        tuple((entity.id,) + trace_values["functions"][:1] + trace_values["logical"][:1] + trace_values["physical"][:1]),
        graph.revision,
    )
    return detail.as_dict()
