"""Shared, side-effect-free helpers for engineering projections."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from typing import Iterable, Mapping

from rflp_lite.domain.entities import Entity, EntityKind, EntityStatus
from rflp_lite.domain.model import ModelGraph
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.trace_rules import (
    F_TO_L, L_TO_P, R_TO_F, R_TO_V, R_TO_VALIDATION, is_technical_requirement,
    requirement_lineage, targets,
)


@dataclass(frozen=True, slots=True)
class ProjectionHeader:
    project_id: str
    revision: int
    snapshot_hash: str

    def as_dict(self) -> Mapping[str, object]:
        return asdict(self)


def header(graph: ModelGraph) -> ProjectionHeader:
    return ProjectionHeader(graph.project_id, graph.revision, graph.snapshot_hash)


def plain(value: object) -> object:
    if is_dataclass(value):
        return plain(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [plain(item) for item in value]
    return value


def entity_card(entity: Entity, *, issue_count: int = 0) -> Mapping[str, object]:
    return {
        "id": entity.id,
        "kind": entity.kind.value,
        "name": entity.meta.name,
        "status": entity.meta.status.value,
        "producer": entity.meta.producer.value,
        "confidence": entity.meta.confidence,
        "issue_count": issue_count,
        "locked": entity.meta.status is EntityStatus.LOCKED,
        "payload": dict(entity.payload),
    }


def entity_name(entity: Entity | None, default: str = "") -> str:
    return entity.meta.name if entity is not None else default


def statement(entity: Entity) -> str:
    for key in ("statement", "text", "requirement", "description"):
        value = entity.payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return entity.meta.name


def issues_by_entity(issues: Iterable[Mapping[str, object]]) -> dict[str, tuple[Mapping[str, object], ...]]:
    result: dict[str, list[Mapping[str, object]]] = {}
    for issue in issues:
        for entity_id in issue.get("entity_ids", ()) or ():
            result.setdefault(str(entity_id), []).append(issue)
    return {key: tuple(value) for key, value in result.items()}


def relation_index(graph: ModelGraph) -> tuple[dict[str, Entity], dict[str, tuple[object, ...]], dict[str, tuple[object, ...]]]:
    entities = graph.entity_index
    outgoing: dict[str, list[object]] = {}
    incoming: dict[str, list[object]] = {}
    for relation in graph.relations:
        outgoing.setdefault(relation.source_id, []).append(relation)
        incoming.setdefault(relation.target_id, []).append(relation)
    return entities, {key: tuple(value) for key, value in outgoing.items()}, {key: tuple(value) for key, value in incoming.items()}


def related_cards(graph: ModelGraph, entity_id: str, *, outgoing: bool, issues: Mapping[str, tuple[Mapping[str, object], ...]]) -> tuple[Mapping[str, object], ...]:
    entities, by_source, by_target = relation_index(graph)
    relations = by_source.get(entity_id, ()) if outgoing else by_target.get(entity_id, ())
    cards = []
    for relation in relations:
        related_id = relation.target_id if outgoing else relation.source_id
        entity = entities.get(related_id)
        if entity is None:
            continue
        card = entity_card(entity, issue_count=len(issues.get(entity.id, ())))
        card["predicate"] = relation.predicate.value
        card["evidence_ids"] = list(relation.evidence_ids)
        cards.append(card)
    return tuple(sorted(cards, key=lambda item: (str(item["kind"]), str(item["id"]), str(item["predicate"]))))


def trace_targets(graph: ModelGraph, requirement_id: str) -> dict[str, tuple[str, ...]]:
    lineage = requirement_lineage(graph, requirement_id)
    functions = tuple(sorted({
        target
        for source_id in lineage
        for target in targets(graph, source_id, R_TO_F)
    }))
    logical = tuple(sorted({target for function_id in functions for target in targets(graph, function_id, F_TO_L)}))
    physical = tuple(sorted({target for logical_id in logical for target in targets(graph, logical_id, L_TO_P)}))
    requirement = graph.entity_index.get(requirement_id)
    if requirement is not None and is_technical_requirement(requirement):
        physical = tuple(sorted({
            *physical,
            *(
                relation.target_id
                for relation in graph.relations
                if relation.source_id == requirement_id
                and relation.predicate is RelationPredicate.SATISFIED_BY
                and graph.entity_index.get(relation.target_id) is not None
                and graph.entity_index[relation.target_id].kind is EntityKind.PHYSICAL_BLOCK
            ),
        }))
    verification = targets(graph, requirement_id, R_TO_V)
    validation = targets(graph, requirement_id, R_TO_VALIDATION)
    return {
        "functions": functions,
        "logical": logical,
        "physical": physical,
        "verification": verification,
        "validation": validation,
    }


def trace_invalid_predicates(graph: ModelGraph, requirement_id: str) -> tuple[str, ...]:
    index = graph.entity_index
    typed_pairs = {
        (EntityKind.REQUIREMENT, EntityKind.FUNCTION),
        (EntityKind.FUNCTION, EntityKind.LOGICAL_COMPONENT),
        (EntityKind.LOGICAL_COMPONENT, EntityKind.PHYSICAL_BLOCK),
        (EntityKind.REQUIREMENT, EntityKind.VERIFICATION_CASE),
        (EntityKind.REQUIREMENT, EntityKind.VALIDATION_CASE),
    }
    invalid: list[str] = []
    for relation in graph.relations:
        if relation.source_id != requirement_id and relation.source_id not in {
            target for stage in trace_targets(graph, requirement_id).values() for target in stage
        }:
            continue
        source = index.get(relation.source_id)
        target = index.get(relation.target_id)
        if source is None or target is None or (source.kind, target.kind) not in typed_pairs:
            continue
        expected = {
            (EntityKind.REQUIREMENT, EntityKind.FUNCTION): R_TO_F,
            (EntityKind.FUNCTION, EntityKind.LOGICAL_COMPONENT): F_TO_L,
            (EntityKind.LOGICAL_COMPONENT, EntityKind.PHYSICAL_BLOCK): L_TO_P,
            (EntityKind.REQUIREMENT, EntityKind.VERIFICATION_CASE): R_TO_V,
            (EntityKind.REQUIREMENT, EntityKind.VALIDATION_CASE): R_TO_VALIDATION,
        }[(source.kind, target.kind)]
        if relation.predicate not in expected.allowed_predicates:
            invalid.append(relation.id)
    return tuple(sorted(set(invalid)))


def requirement_trace_status(graph: ModelGraph, requirement: Entity) -> tuple[str, tuple[str, ...], dict[str, tuple[str, ...]]]:
    trace = trace_targets(graph, requirement.id)
    invalid = trace_invalid_predicates(graph, requirement.id)
    if requirement.meta.status in {EntityStatus.REJECTED, EntityStatus.DEPRECATED}:
        return "REJECTED", ("rejected",), trace
    if invalid:
        return "INVALID_PREDICATE", ("invalid_predicate",), trace
    gaps = tuple(stage for stage, values in (("function", trace["functions"]), ("logical", trace["logical"]), ("physical", trace["physical"]), ("verification", trace["verification"]), ("validation", trace["validation"])) if not values)
    gap_codes = {"function": "MISSING_FUNCTION", "logical": "MISSING_LOGICAL", "physical": "MISSING_PHYSICAL", "verification": "MISSING_VERIFICATION", "validation": "MISSING_VALIDATION"}
    status = "PASS" if not gaps else gap_codes[gaps[0]] if len(gaps) == 1 else "BLOCKED"
    return status, gaps, trace


def as_payload(value: object) -> object:
    return plain(value)
