"""Per-requirement coverage for the product's vertical generation stages."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum

from rflp_lite.domain.entities import Entity, EntityKind, EntityStatus
from rflp_lite.domain.model import ModelGraph
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.trace_rules import (
    is_technical_requirement,
    requirement_lineage,
)
from rflp_lite.methodology.coverage_status import coverage_result


class CoverageStage(StrEnum):
    FUNCTIONAL = "functional"
    LOGICAL = "logical"
    PHYSICAL = "physical"
    VERIFICATION_VALIDATION = "verification_validation"


_INACTIVE = frozenset({EntityStatus.REJECTED, EntityStatus.DEPRECATED})
_TRACE_READY = frozenset({
    EntityStatus.VALIDATED,
    EntityStatus.ACCEPTED,
    EntityStatus.LOCKED,
})


@dataclass(frozen=True, slots=True)
class RequirementCoverageRow:
    requirement_id: str
    stage: str
    function_ids: tuple[str, ...] = ()
    logical_component_ids: tuple[str, ...] = ()
    physical_ids: tuple[str, ...] = ()
    verification_case_ids: tuple[str, ...] = ()
    validation_case_ids: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    path: tuple[str, ...] = ()

    def as_dict(self) -> Mapping[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class VerticalCoverage:
    stage: str
    rows: tuple[RequirementCoverageRow, ...]
    passed: bool

    @property
    def covered_count(self) -> int:
        return sum(not row.missing for row in self.rows)

    @property
    def missing_requirement_ids(self) -> tuple[str, ...]:
        return tuple(row.requirement_id for row in self.rows if row.missing)

    @property
    def coverage(self) -> Mapping[str, object]:
        return coverage_result(self.covered_count, len(self.rows))

    def as_check(self, *, max_gaps: int = 24) -> Mapping[str, object]:
        return {
            "id": f"requirement_coverage:{self.stage}",
            "stage": self.stage,
            "passed": self.passed,
            "status": self.coverage["status"],
            "coverage": self.coverage["coverage"],
            "requirement_count": len(self.rows),
            "covered_count": self.covered_count,
            "missing_requirement_ids": list(self.missing_requirement_ids),
            "gaps": [
                row.as_dict()
                for row in self.rows
                if row.missing
            ][:max(0, int(max_gaps))],
        }


@dataclass(frozen=True, slots=True)
class CanonicalRequirementTrace:
    """One semantic, ready-only trace projection for a Requirement."""

    requirement_id: str
    function_ids: tuple[str, ...]
    logical_component_ids: tuple[str, ...]
    physical_ids: tuple[str, ...]
    verification_case_ids: tuple[str, ...]
    validation_case_ids: tuple[str, ...]
    gaps: tuple[str, ...]
    stage_coverage: Mapping[str, bool]
    primary_path: tuple[str, ...]
    complete: bool

    def target_dict(self) -> Mapping[str, tuple[str, ...]]:
        return {
            "functions": self.function_ids,
            "logical": self.logical_component_ids,
            "physical": self.physical_ids,
            "verification": self.verification_case_ids,
            "validation": self.validation_case_ids,
        }

    def as_dict(self) -> Mapping[str, object]:
        return {
            "requirement_id": self.requirement_id,
            **{key: list(value) for key, value in self.target_dict().items()},
            "gaps": list(self.gaps),
            "stage_coverage": dict(self.stage_coverage),
            "primary_path": list(self.primary_path),
            "complete": self.complete,
        }


def resolve_requirement_trace(
    graph: ModelGraph,
    requirement_id: str,
) -> CanonicalRequirementTrace:
    """Resolve one Requirement into the canonical ready-only trace contract."""

    requirement = graph.entity_index.get(requirement_id)
    if requirement is None or requirement.kind is not EntityKind.REQUIREMENT:
        return CanonicalRequirementTrace(
            requirement_id,
            (), (), (), (), (),
            ("requirement",),
            {
                "functional": False,
                "logical": False,
                "physical": False,
                "verification": False,
                "validation": False,
            },
            (requirement_id,),
            False,
        )

    rflp = _resolve_row(graph, requirement, CoverageStage.PHYSICAL)
    assurance = _resolve_row(
        graph,
        requirement,
        CoverageStage.VERIFICATION_VALIDATION,
    )
    stage_coverage = {
        "functional": bool(rflp.function_ids),
        "logical": bool(rflp.logical_component_ids),
        "physical": bool(rflp.physical_ids),
        "verification": bool(assurance.verification_case_ids)
        and "verification_scope" not in assurance.missing,
        "validation": bool(assurance.validation_case_ids)
        and "validation_scope" not in assurance.missing,
    }
    gaps = tuple(
        _canonical_gap_name(value)
        for value in (*rflp.missing, *assurance.missing)
    )
    primary_path = [requirement_id]
    for entity_id in (
        rflp.function_ids,
        rflp.logical_component_ids,
        rflp.physical_ids,
    ):
        if entity_id:
            primary_path.append(entity_id[0])
    return CanonicalRequirementTrace(
        requirement_id,
        rflp.function_ids,
        rflp.logical_component_ids,
        rflp.physical_ids,
        assurance.verification_case_ids,
        assurance.validation_case_ids,
        gaps,
        stage_coverage,
        tuple(primary_path),
        not gaps,
    )


def resolve_rflp_paths(
    graph: ModelGraph,
    requirement_id: str,
) -> tuple[tuple[str, ...], ...]:
    """Enumerate all deterministic, ready-only R→F→L→P paths."""

    requirement = graph.entity_index.get(requirement_id)
    if requirement is None or requirement.kind is not EntityKind.REQUIREMENT:
        return ()
    row = _resolve_row(graph, requirement, CoverageStage.PHYSICAL)
    paths = [
        (requirement_id, function_id, logical_id, physical_id)
        for function_id in row.function_ids
        for logical_id in _target_ids(
            graph,
            (function_id,),
            (RelationPredicate.ALLOCATED_TO, RelationPredicate.SATISFIED_BY),
            EntityKind.LOGICAL_COMPONENT,
        )
        for physical_id in _target_ids(
            graph,
            (logical_id,),
            (RelationPredicate.ALLOCATED_TO, RelationPredicate.REALIZED_BY),
            EntityKind.PHYSICAL_BLOCK,
        )
        if logical_id in row.logical_component_ids
        and physical_id in row.physical_ids
    ]
    return tuple(sorted(paths))


def _canonical_gap_name(value: str) -> str:
    return {
        "logical_component": "logical",
    }.get(value, value)


def resolve_vertical_coverage(
    graph: ModelGraph,
    stage: CoverageStage | str,
) -> VerticalCoverage:
    """Resolve typed coverage for every Requirement relevant to ``stage``."""

    stage_name = str(getattr(stage, "value", stage))
    try:
        stage_value = CoverageStage(stage_name)
    except ValueError as exc:
        raise ValueError(f"unsupported vertical coverage stage: {stage_name}") from exc

    rows = tuple(
        _resolve_row(graph, requirement, stage_value)
        for requirement in _stage_requirements(graph, stage_value)
    )
    # ``all(())`` is vacuously true, but an empty Requirement set is not a
    # completed engineering stage.  Keep stage coverage non-vacuous just like
    # strict Closure and the phase gates.
    return VerticalCoverage(stage_name, rows, bool(rows) and all(not row.missing for row in rows))


def build_requirement_worklist(
    graph: ModelGraph,
    stage: CoverageStage | str,
    *,
    max_items: int | None = 24,
) -> Mapping[str, object]:
    """Expose compact, per-requirement work items for a vertical LLM call.

    The coverage resolver remains the source of truth.  This projection adds
    the current canonical targets so a stage can repair an exact requirement
    without relying on aggregate entity counts.
    """

    coverage = resolve_vertical_coverage(graph, stage)
    limit = (
        len(coverage.rows)
        if max_items is None
        else max(0, int(max_items))
    )
    items = []
    for row in coverage.rows[:limit]:
        requirement = graph.entity_index[row.requirement_id]
        statement = requirement.payload.get("statement", requirement.meta.name)
        items.append({
            "requirement_id": row.requirement_id,
            "statement": str(statement).strip() or requirement.meta.name,
            "current": {
                "function_ids": list(row.function_ids),
                "logical_component_ids": list(row.logical_component_ids),
                "physical_ids": list(row.physical_ids),
                "verification_case_ids": list(row.verification_case_ids),
                "validation_case_ids": list(row.validation_case_ids),
            },
            "missing": list(row.missing),
            "path": list(row.path),
        })
    return {
        "stage": coverage.stage,
        "passed": coverage.passed,
        "items": items,
        "total_count": len(coverage.rows),
        "truncated": len(coverage.rows) > limit,
    }


def _stage_requirements(
    graph: ModelGraph,
    stage: CoverageStage,
) -> tuple[Entity, ...]:
    requirements = tuple(
        entity
        for entity in graph.entities
        if entity.kind is EntityKind.REQUIREMENT
        and entity.meta.status not in _INACTIVE
        and (
            stage in {CoverageStage.PHYSICAL, CoverageStage.VERIFICATION_VALIDATION}
            or not is_technical_requirement(entity)
        )
    )
    return tuple(sorted(requirements, key=lambda entity: entity.id))


def _resolve_row(
    graph: ModelGraph,
    requirement: Entity,
    stage: CoverageStage,
) -> RequirementCoverageRow:
    source_ids = _source_ids(graph, requirement.id)
    function_ids = _target_ids(
        graph,
        source_ids,
        (RelationPredicate.SATISFIED_BY,),
        EntityKind.FUNCTION,
    )
    logical_component_ids = _target_ids(
        graph,
        function_ids,
        (RelationPredicate.ALLOCATED_TO, RelationPredicate.SATISFIED_BY),
        EntityKind.LOGICAL_COMPONENT,
    )
    physical_ids = _target_ids(
        graph,
        logical_component_ids,
        (RelationPredicate.ALLOCATED_TO, RelationPredicate.REALIZED_BY),
        EntityKind.PHYSICAL_BLOCK,
    )
    if is_technical_requirement(requirement):
        physical_ids = tuple(dict.fromkeys((
            *physical_ids,
            *_target_ids(
                graph,
                source_ids,
                (RelationPredicate.SATISFIED_BY,),
                EntityKind.PHYSICAL_BLOCK,
            ),
        )))
    verification_case_ids = _target_ids(
        graph,
        (requirement.id,),
        (RelationPredicate.VERIFIED_BY,),
        EntityKind.VERIFICATION_CASE,
    )
    validation_case_ids = _target_ids(
        graph,
        (requirement.id,),
        (RelationPredicate.VALIDATED_BY,),
        EntityKind.VALIDATION_CASE,
    )
    missing = _missing_for_stage(
        graph,
        requirement,
        stage,
        function_ids,
        logical_component_ids,
        physical_ids,
        verification_case_ids,
        validation_case_ids,
    )
    return RequirementCoverageRow(
        requirement.id,
        stage.value,
        function_ids,
        logical_component_ids,
        physical_ids,
        verification_case_ids,
        validation_case_ids,
        missing,
        _path(
            requirement.id,
            stage,
            function_ids,
            logical_component_ids,
            physical_ids,
            verification_case_ids,
            validation_case_ids,
        ),
    )


def _missing_for_stage(
    graph: ModelGraph,
    requirement: Entity,
    stage: CoverageStage,
    function_ids: tuple[str, ...],
    logical_component_ids: tuple[str, ...],
    physical_ids: tuple[str, ...],
    verification_case_ids: tuple[str, ...],
    validation_case_ids: tuple[str, ...],
) -> tuple[str, ...]:
    missing: list[str] = []
    if stage is CoverageStage.FUNCTIONAL:
        if not function_ids:
            missing.append("function")
    elif stage is CoverageStage.LOGICAL:
        if not function_ids:
            missing.append("function")
        if not logical_component_ids:
            missing.append("logical_component")
    elif stage is CoverageStage.PHYSICAL:
        if not is_technical_requirement(requirement):
            if not function_ids:
                missing.append("function")
            if not logical_component_ids:
                missing.append("logical_component")
        if not physical_ids:
            missing.append("physical")
    else:
        if not verification_case_ids:
            missing.append("verification")
        elif not _has_matching_scope(graph, requirement.id, verification_case_ids):
            missing.append("verification_scope")
        if not validation_case_ids:
            missing.append("validation")
        elif not _has_matching_scope(graph, requirement.id, validation_case_ids):
            missing.append("validation_scope")
    return tuple(missing)


def _has_matching_scope(
    graph: ModelGraph,
    requirement_id: str,
    case_ids: tuple[str, ...],
) -> bool:
    expected = _canonical_scope(graph, requirement_id)
    return any(
        case_id in graph.entity_index
        and _scope_matches(graph.entity_index[case_id], expected)
        for case_id in case_ids
    )


def _source_ids(graph: ModelGraph, requirement_id: str) -> tuple[str, ...]:
    index = graph.entity_index
    source_ids = [requirement_id, *requirement_lineage(graph, requirement_id)]
    requirement = index.get(requirement_id)
    payload_sources = requirement.payload.get("source_requirement_ids", ()) if requirement else ()
    if isinstance(payload_sources, (list, tuple, set)):
        source_ids.extend(
            str(source_id)
            for source_id in payload_sources
            if str(source_id) in index
            and index[str(source_id)].kind is EntityKind.REQUIREMENT
        )
    return tuple(dict.fromkeys(source_ids))


def _canonical_scope(
    graph: ModelGraph,
    requirement_id: str,
) -> Mapping[str, tuple[str, ...]]:
    requirement = graph.entity_index.get(requirement_id)
    if requirement is None or requirement.kind is not EntityKind.REQUIREMENT:
        return {
            "requirement_ids": (requirement_id,),
            "function_ids": (),
            "logical_component_ids": (),
            "physical_ids": (),
        }
    source_ids = _source_ids(graph, requirement_id)
    function_ids = _target_ids(
        graph,
        source_ids,
        (RelationPredicate.SATISFIED_BY,),
        EntityKind.FUNCTION,
    )
    logical_component_ids = _target_ids(
        graph,
        function_ids,
        (RelationPredicate.ALLOCATED_TO, RelationPredicate.SATISFIED_BY),
        EntityKind.LOGICAL_COMPONENT,
    )
    physical_ids = _target_ids(
        graph,
        logical_component_ids,
        (RelationPredicate.ALLOCATED_TO, RelationPredicate.REALIZED_BY),
        EntityKind.PHYSICAL_BLOCK,
    )
    if is_technical_requirement(requirement):
        physical_ids = tuple(dict.fromkeys((
            *physical_ids,
            *_target_ids(
                graph,
                source_ids,
                (RelationPredicate.SATISFIED_BY,),
                EntityKind.PHYSICAL_BLOCK,
            ),
        )))
    return {
        "requirement_ids": (requirement_id,),
        "function_ids": function_ids,
        "logical_component_ids": logical_component_ids,
        "physical_ids": physical_ids,
    }


def _scope_matches(
    case: Entity,
    expected: Mapping[str, tuple[str, ...]],
) -> bool:
    aliases = {"logical_component_ids": ("logical_component_ids", "logical_ids")}
    for field, expected_ids in expected.items():
        actual_ids = ()
        for key in aliases.get(field, (field,)):
            value = case.payload.get(key)
            if isinstance(value, (list, tuple, set)):
                actual_ids = tuple(str(item) for item in value)
                break
        if set(actual_ids) != set(expected_ids):
            return False
    return True


def _target_ids(
    graph: ModelGraph,
    source_ids: tuple[str, ...],
    predicates: tuple[RelationPredicate, ...],
    target_kind: EntityKind,
) -> tuple[str, ...]:
    index = graph.entity_index
    source_set = set(source_ids)
    predicate_set = set(predicates)
    return tuple(sorted({
        relation.target_id
        for relation in graph.relations
        if relation.source_id in source_set
        and relation.predicate in predicate_set
        and index.get(relation.target_id) is not None
        and index[relation.target_id].kind is target_kind
        and index[relation.target_id].meta.status in _TRACE_READY
    }))


def _path(
    requirement_id: str,
    stage: CoverageStage,
    function_ids: tuple[str, ...],
    logical_component_ids: tuple[str, ...],
    physical_ids: tuple[str, ...],
    verification_case_ids: tuple[str, ...],
    validation_case_ids: tuple[str, ...],
) -> tuple[str, ...]:
    values = [requirement_id]
    if function_ids and stage is not CoverageStage.VERIFICATION_VALIDATION:
        values.append(function_ids[0])
    if logical_component_ids and stage is not CoverageStage.FUNCTIONAL:
        values.append(logical_component_ids[0])
    if physical_ids and stage is CoverageStage.PHYSICAL:
        values.append(physical_ids[0])
    if stage is CoverageStage.VERIFICATION_VALIDATION:
        if function_ids:
            values.append(function_ids[0])
        if logical_component_ids:
            values.append(logical_component_ids[0])
        if physical_ids:
            values.append(physical_ids[0])
        if verification_case_ids:
            values.append(verification_case_ids[0])
        if validation_case_ids:
            values.append(validation_case_ids[0])
    return tuple(values)
