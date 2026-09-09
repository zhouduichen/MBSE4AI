"""Stable Requirement Coverage Matrix built from named trace rules."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping

from rflp_lite.domain.entities import EntityKind, EntityStatus
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.trace_rules import (
    F_TO_L, L_TO_P, R_TO_F, R_TO_V, R_TO_VALIDATION, best_partial_path, rflp_paths, targets,
)


@dataclass(frozen=True, slots=True)
class RequirementCoverageRow:
    requirement_id: str
    evidence: bool
    functions: tuple[str, ...]
    logical_components: tuple[str, ...]
    physical_blocks: tuple[str, ...]
    verification_cases: tuple[str, ...]
    validation_cases: tuple[str, ...]
    hazards: tuple[str, ...]
    passed: bool
    gaps: tuple[str, ...]
    paths: tuple[tuple[str, ...], ...] = ()
    best_path: tuple[str, ...] = ()

    def as_dict(self) -> Mapping[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CoverageMatrix:
    rows: tuple[RequirementCoverageRow, ...]
    metrics: Mapping[str, object]

    def as_dict(self) -> Mapping[str, object]:
        return {"rows": [row.as_dict() for row in self.rows], "metrics": dict(self.metrics)}


def _accepted_requirements(graph: ModelGraph):
    return tuple(sorted(
        (entity for entity in graph.entities
         if entity.kind is EntityKind.REQUIREMENT and entity.meta.status is EntityStatus.ACCEPTED),
        key=lambda entity: entity.id,
    ))


def _evidence_coverage(graph: ModelGraph, requirement_id: str) -> bool:
    index = graph.entity_index
    requirement = index[requirement_id]
    if requirement.meta.evidence_ids:
        return True
    return any(
        requirement_id in {relation.source_id, relation.target_id} and bool(relation.evidence_ids)
        for relation in graph.relations
    )


def _hazards_for_requirement(graph: ModelGraph, requirement_id: str) -> tuple[str, ...]:
    return tuple(sorted(
        relation.source_id for relation in graph.relations
        if relation.target_id == requirement_id
        and relation.predicate.value == "mitigatedBy"
        and graph.entity_index.get(relation.source_id)
        and graph.entity_index[relation.source_id].kind in {EntityKind.HAZARD, EntityKind.FAILURE_MODE}
    ))


def build_requirement_coverage(graph: ModelGraph) -> CoverageMatrix:
    rows: list[RequirementCoverageRow] = []
    for requirement in _accepted_requirements(graph):
        requirement_id = requirement.id
        functions = tuple(sorted(targets(graph, requirement_id, R_TO_F)))
        logical = tuple(sorted({
            logical_id for function_id in functions
            for logical_id in targets(graph, function_id, F_TO_L)
        }))
        physical = tuple(sorted({
            physical_id for logical_id in logical
            for physical_id in targets(graph, logical_id, L_TO_P)
        }))
        verification = tuple(sorted(targets(graph, requirement_id, R_TO_V)))
        validation = tuple(sorted(targets(graph, requirement_id, R_TO_VALIDATION)))
        paths = rflp_paths(graph, requirement_id)
        gaps: list[str] = []
        if not functions:
            gaps.append("function")
        if not logical:
            gaps.append("logical")
        if not physical:
            gaps.append("physical")
        if not verification:
            gaps.append("verification")
        if not _evidence_coverage(graph, requirement_id):
            gaps.append("evidence")
        rows.append(RequirementCoverageRow(
            requirement_id, _evidence_coverage(graph, requirement_id), functions, logical,
            physical, verification, validation, _hazards_for_requirement(graph, requirement_id),
            not gaps, tuple(gaps), paths, paths[0] if paths else best_partial_path(graph, requirement_id),
        ))
    total = len(rows)
    count = lambda predicate: sum(1 for row in rows if predicate(row))
    broken_relations = sum(
        1 for relation in graph.relations
        if relation.source_id not in graph.entity_index or relation.target_id not in graph.entity_index
    )
    orphan_entities = sum(
        1 for entity in graph.entities
        if not entity.meta.source_ids and not entity.meta.evidence_ids
        and not any(entity.id in {relation.source_id, relation.target_id} for relation in graph.relations)
    )
    metrics = {
        "requirement_count": total,
        "r_to_f_coverage": count(lambda row: bool(row.functions)) / total if total else 1.0,
        "r_to_f_to_l_coverage": count(lambda row: bool(row.logical_components)) / total if total else 1.0,
        "r_to_f_to_l_to_p_coverage": count(lambda row: bool(row.physical_blocks)) / total if total else 1.0,
        "r_to_v_coverage": count(lambda row: bool(row.verification_cases)) / total if total else 1.0,
        "evidence_coverage": count(lambda row: row.evidence) / total if total else 1.0,
        "verification_pass_criteria_coverage": _verification_pass_criteria_coverage(graph),
        "orphan_entity_count": orphan_entities,
        "broken_relation_count": broken_relations,
    }
    return CoverageMatrix(tuple(rows), metrics)


def _verification_pass_criteria_coverage(graph: ModelGraph) -> float:
    cases = [entity for entity in graph.entities if entity.kind is EntityKind.VERIFICATION_CASE]
    if not cases:
        return 1.0
    return sum(1 for entity in cases if str(entity.payload.get("method", "")).strip() and str(entity.payload.get("pass_criteria", "")).strip()) / len(cases)
