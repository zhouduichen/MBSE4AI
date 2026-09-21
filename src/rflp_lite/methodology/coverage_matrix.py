"""Stable Requirement Coverage Matrix built from named trace rules."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping

from rflp_lite.domain.entities import EntityKind, EntityStatus
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.vertical_coverage import (
    resolve_requirement_trace,
    resolve_rflp_paths,
)
from rflp_lite.methodology.vv_contract import missing_vv_plan_fields
from rflp_lite.methodology.coverage_status import coverage_result


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
         if entity.kind is EntityKind.REQUIREMENT
         and entity.meta.status in {
             EntityStatus.VALIDATED,
             EntityStatus.ACCEPTED,
             EntityStatus.LOCKED,
         }),
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
        trace = resolve_requirement_trace(graph, requirement_id)
        functions = trace.function_ids
        logical = trace.logical_component_ids
        physical = trace.physical_ids
        verification = trace.verification_case_ids if trace.stage_coverage["verification"] else ()
        validation = trace.validation_case_ids if trace.stage_coverage["validation"] else ()
        paths = resolve_rflp_paths(graph, requirement_id)
        gaps = list(trace.gaps)
        if not _evidence_coverage(graph, requirement_id):
            gaps.append("evidence")
        best_path = paths[0] if paths else trace.primary_path
        rows.append(RequirementCoverageRow(
            requirement_id, _evidence_coverage(graph, requirement_id), functions, logical,
            physical, verification, validation, _hazards_for_requirement(graph, requirement_id),
            not gaps, tuple(gaps), paths, best_path,
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
    ratio = lambda value: value / total if total else None
    complete_count = count(lambda row: row.passed)
    aggregate = coverage_result(complete_count, total)
    metrics = {
        "requirement_count": total,
        "covered_count": complete_count,
        "coverage": aggregate["coverage"],
        "status": aggregate["status"],
        "coverage_status": aggregate["status"],
        "r_to_f_coverage": ratio(count(lambda row: bool(row.functions))),
        "r_to_f_to_l_coverage": ratio(count(lambda row: bool(row.logical_components))),
        "r_to_f_to_l_to_p_coverage": ratio(count(lambda row: bool(row.physical_blocks))),
        "r_to_v_coverage": ratio(count(lambda row: bool(row.verification_cases))),
        "r_to_validation_coverage": ratio(count(lambda row: bool(row.validation_cases))),
        "evidence_coverage": ratio(count(lambda row: row.evidence)),
        "verification_pass_criteria_coverage": _verification_pass_criteria_coverage(graph),
        "orphan_entity_count": orphan_entities,
        "broken_relation_count": broken_relations,
    }
    return CoverageMatrix(tuple(rows), metrics)


def _verification_pass_criteria_coverage(graph: ModelGraph) -> float | None:
    cases = [entity for entity in graph.entities if entity.kind is EntityKind.VERIFICATION_CASE]
    if not cases:
        return None
    return sum(1 for entity in cases if not missing_vv_plan_fields(entity.payload)) / len(cases)
