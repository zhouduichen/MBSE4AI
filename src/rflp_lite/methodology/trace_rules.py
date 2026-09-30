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


@dataclass(frozen=True, slots=True)
class RequirementTraceScope:
    """Canonical downstream scope used by V&V and completion checks."""

    requirement_ids: tuple[str, ...]
    function_ids: tuple[str, ...]
    logical_component_ids: tuple[str, ...]
    physical_ids: tuple[str, ...]

    def as_dict(self):
        return {
            "requirement_ids": list(self.requirement_ids),
            "function_ids": list(self.function_ids),
            "logical_component_ids": list(self.logical_component_ids),
            "physical_ids": list(self.physical_ids),
        }


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


def requirement_trace_scope(graph: ModelGraph, requirement_id: str) -> RequirementTraceScope:
    """Resolve the complete primary downstream scope for one requirement."""

    index = graph.entity_index
    requirement = index.get(requirement_id)
    if requirement is None or requirement.kind is not EntityKind.REQUIREMENT:
        return RequirementTraceScope((requirement_id,), (), (), ())
    lineage = set(requirement_lineage(graph, requirement_id))
    source_ids = {requirement_id, *lineage}
    payload_sources = requirement.payload.get("source_requirement_ids", ())
    if isinstance(payload_sources, (list, tuple, set)):
        source_ids.update(
            str(item)
            for item in payload_sources
            if str(item) in index and index[str(item)].kind is EntityKind.REQUIREMENT
        )
    functions = {
        target_id for source_id in source_ids
        for target_id in targets(graph, source_id, R_TO_F)
    }
    logical_components = {
        target_id for function_id in functions
        for target_id in targets(graph, function_id, F_TO_L)
    }
    physical = {
        target_id for logical_id in logical_components
        for target_id in targets(graph, logical_id, L_TO_P)
    }
    physical.update(
        relation.target_id
        for relation in graph.relations
        if relation.source_id in source_ids
        and relation.predicate is RelationPredicate.SATISFIED_BY
        and index.get(relation.target_id) is not None
        and index[relation.target_id].kind is EntityKind.PHYSICAL_BLOCK
    )
    return RequirementTraceScope(
        (requirement_id,),
        tuple(sorted(functions)),
        tuple(sorted(logical_components)),
        tuple(sorted(physical)),
    )


def vv_scope_matches(graph: ModelGraph, requirement_id: str, case) -> bool:
    """Check that a V&V case payload matches the graph-derived scope."""

    expected = requirement_trace_scope(graph, requirement_id).as_dict()
    payload = case.payload
    aliases = {
        "logical_component_ids": ("logical_component_ids", "logical_ids"),
    }
    for field, expected_ids in expected.items():
        actual_ids = ()
        for key in aliases.get(field, (field,)):
            value = payload.get(key)
            if isinstance(value, (list, tuple, set)):
                actual_ids = value
                break
        if set(str(item) for item in actual_ids) != set(expected_ids):
            return False
    return True


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
