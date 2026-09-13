"""Named, predicate-aware trace rules for MBSE coverage."""

from __future__ import annotations

from dataclasses import dataclass

from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.model import ModelGraph
from rflp_lite.domain.relations import RelationPredicate


@dataclass(frozen=True, slots=True)
class TraceRule:
    name: str
    source_kind: EntityKind
    target_kind: EntityKind
    allowed_predicates: frozenset[RelationPredicate]


R_TO_F = TraceRule(
    "requirement_to_function", EntityKind.REQUIREMENT, EntityKind.FUNCTION,
    frozenset({RelationPredicate.SATISFIED_BY}),
)
F_TO_L = TraceRule(
    "function_to_logical", EntityKind.FUNCTION, EntityKind.LOGICAL_COMPONENT,
    frozenset({RelationPredicate.ALLOCATED_TO, RelationPredicate.SATISFIED_BY}),
)
L_TO_P = TraceRule(
    "logical_to_physical", EntityKind.LOGICAL_COMPONENT, EntityKind.PHYSICAL_BLOCK,
    frozenset({RelationPredicate.ALLOCATED_TO, RelationPredicate.REALIZED_BY}),
)
R_TO_V = TraceRule(
    "requirement_to_verification", EntityKind.REQUIREMENT, EntityKind.VERIFICATION_CASE,
    frozenset({RelationPredicate.VERIFIED_BY}),
)
R_TO_VALIDATION = TraceRule(
    "requirement_to_validation", EntityKind.REQUIREMENT, EntityKind.VALIDATION_CASE,
    frozenset({RelationPredicate.VALIDATED_BY}),
)
MITIGATION = TraceRule(
    "hazard_to_mitigation", EntityKind.HAZARD, EntityKind.REQUIREMENT,
    frozenset({RelationPredicate.MITIGATED_BY}),
)

TRACE_RULES = (R_TO_F, F_TO_L, L_TO_P, R_TO_V, R_TO_VALIDATION, MITIGATION)


def is_technical_requirement(entity) -> bool:
    return (
        entity.kind is EntityKind.REQUIREMENT
        and str(entity.payload.get("level", "")).strip().lower() == "technical"
    )


def requirement_lineage(graph: ModelGraph, requirement_id: str) -> tuple[str, ...]:
    """Return stable root requirements for a derived requirement."""

    index = graph.entity_index
    pending = [requirement_id]
    visited: set[str] = set()
    roots: set[str] = set()
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        parent_ids = {
            relation.target_id
            for relation in graph.relations
            if relation.source_id == current
            and relation.predicate is RelationPredicate.DERIVED_FROM
            and index.get(relation.target_id) is not None
            and index[relation.target_id].kind is EntityKind.REQUIREMENT
        }
        if parent_ids:
            pending.extend(sorted(parent_ids))
        else:
            roots.add(current)
    return tuple(sorted(roots or {requirement_id}))


def targets(graph: ModelGraph, source_id: str, rule: TraceRule) -> tuple[str, ...]:
    """Return only typed targets connected by one of ``rule`` predicates."""

    index = graph.entity_index
    return tuple(sorted({
        relation.target_id
        for relation in graph.relations
        if relation.source_id == source_id
        and relation.predicate in rule.allowed_predicates
        and index.get(relation.target_id) is not None
        and index[relation.target_id].kind is rule.target_kind
    }))


def direct_paths(graph: ModelGraph, source_id: str, rule: TraceRule) -> tuple[tuple[str, ...], ...]:
    return tuple((source_id, target_id) for target_id in targets(graph, source_id, rule))


def rflp_paths(graph: ModelGraph, requirement_id: str) -> tuple[tuple[str, ...], ...]:
    """Enumerate all valid Requirement → Function → Logical → Physical paths."""

    paths: list[tuple[str, ...]] = []
    for function_id in targets(graph, requirement_id, R_TO_F):
        for logical_id in targets(graph, function_id, F_TO_L):
            for physical_id in targets(graph, logical_id, L_TO_P):
                paths.append((requirement_id, function_id, logical_id, physical_id))
    return tuple(sorted(paths))


def best_partial_path(graph: ModelGraph, requirement_id: str) -> tuple[str, ...]:
    """Return a stable longest valid prefix for diagnostics on a failed trace."""

    candidates: list[tuple[str, ...]] = [(requirement_id,)]
    for function_id in targets(graph, requirement_id, R_TO_F):
        candidates.append((requirement_id, function_id))
        for logical_id in targets(graph, function_id, F_TO_L):
            candidates.append((requirement_id, function_id, logical_id))
            for physical_id in targets(graph, logical_id, L_TO_P):
                candidates.append((requirement_id, function_id, logical_id, physical_id))
    return max(sorted(candidates), key=len)


def relation_is_valid_trace(graph: ModelGraph, source_id: str, target_id: str, predicate: RelationPredicate) -> bool:
    """Check whether one concrete edge is a member of any named trace rule."""

    index = graph.entity_index
    source = index.get(source_id)
    target = index.get(target_id)
    if source is None or target is None:
        return False
    return any(
        rule.source_kind is source.kind
        and rule.target_kind is target.kind
        and predicate in rule.allowed_predicates
        for rule in TRACE_RULES
    )
