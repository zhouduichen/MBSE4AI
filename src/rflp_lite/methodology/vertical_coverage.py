"""Per-requirement coverage for the product's vertical generation stages."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Mapping

from rflp_lite.domain.entities import Entity, EntityKind, EntityStatus
from rflp_lite.domain.model import ModelGraph
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.trace_rules import (
    is_technical_requirement,
    requirement_lineage,
    vv_scope_matches,
)


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

    def as_check(self, *, max_gaps: int = 24) -> Mapping[str, object]:
        return {
            "id": f"requirement_coverage:{self.stage}",
            "stage": self.stage,
            "passed": self.passed,
            "requirement_count": len(self.rows),
            "covered_count": self.covered_count,
            "missing_requirement_ids": list(self.missing_requirement_ids),
            "gaps": [
                row.as_dict()
                for row in self.rows
                if row.missing
            ][:max(0, int(max_gaps))],
        }


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
    return VerticalCoverage(stage_name, rows, all(not row.missing for row in rows))


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
    source_ids = tuple(dict.fromkeys((requirement.id, *requirement_lineage(graph, requirement.id))))
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
    return any(
        case_id in graph.entity_index
        and vv_scope_matches(graph, requirement_id, graph.entity_index[case_id])
        for case_id in case_ids
    )


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
