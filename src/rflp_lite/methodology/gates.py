"""Deterministic Phase Gates; semantic critics can add diagnostics later."""

from __future__ import annotations

from dataclasses import dataclass

from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.contracts import Phase
from rflp_lite.methodology.coverage_matrix import build_requirement_coverage
from rflp_lite.methodology.coverage import CoverageGap, CoverageReport, evaluate
from rflp_lite.methodology.trace_rules import F_TO_L, L_TO_P, R_TO_F, R_TO_V, R_TO_VALIDATION


@dataclass(frozen=True, slots=True)
class GateResult:
    gate_id: str
    passed: bool
    issues: tuple[CoverageGap, ...] = ()
    rollback_phase: Phase | None = None
    checks: tuple[dict[str, object], ...] = ()


def _has(graph: ModelGraph, *kinds: EntityKind) -> bool:
    present = {entity.kind for entity in graph.entities}
    return all(kind in present for kind in kinds)


def operational_gate(graph: ModelGraph) -> GateResult:
    report = evaluate(graph)
    issues = tuple(gap for gap in report.gaps if gap.root_cause in {"stakeholder", "lifecycle", "scenario", "requirement"})
    return GateResult("O-Gate", not issues, issues, Phase.OPERATIONAL if issues else None)


def functional_gate(graph: ModelGraph) -> GateResult:
    issues: list[CoverageGap] = []
    checks: list[dict[str, object]] = []
    if not _has(graph, EntityKind.FUNCTION):
        issues.append(CoverageGap("missing_function", "function"))
    matrix = build_requirement_coverage(graph)
    for row in matrix.rows:
        linked = bool(row.functions)
        checks.append({
            "id": f"requirement-to-function:{row.requirement_id}",
            "passed": linked,
            "path": list(row.best_path[:2]),
            "missing_stage": "function" if not linked else None,
            "expected_predicates": [item.value for item in sorted(R_TO_F.allowed_predicates, key=lambda item: item.value)],
        })
        if not linked:
            issues.append(CoverageGap("broken_requirement_function_trace", "function", (row.requirement_id,)))
    return GateResult("F-Gate", not issues, tuple(issues), Phase.FUNCTIONAL if issues else None, tuple(checks))


def rflp_gate(graph: ModelGraph) -> GateResult:
    required = (EntityKind.REQUIREMENT, EntityKind.FUNCTION, EntityKind.LOGICAL_COMPONENT, EntityKind.PHYSICAL_BLOCK)
    if not _has(graph, *required):
        return GateResult("P-Gate", False, (CoverageGap("incomplete_rflp_chain", "architecture"),), Phase.FUNCTIONAL, ())
    index = graph.entity_index
    matrix = build_requirement_coverage(graph)
    accepted_requirements = {row.requirement_id for row in matrix.rows}
    if not accepted_requirements:
        return GateResult("P-Gate", True, checks=())
    missing = []
    checks: list[dict[str, object]] = []
    for row in matrix.rows:
        physical = bool(row.physical_blocks)
        missing_stage = row.gaps[0] if row.gaps else None
        checks.append({
            "id": f"requirement-rflp:{row.requirement_id}",
            "passed": physical,
            "path": list(row.best_path),
            "missing_stage": missing_stage,
            "expected_predicates": [item.value for item in sorted(
                (R_TO_F.allowed_predicates | F_TO_L.allowed_predicates | L_TO_P.allowed_predicates),
                key=lambda item: item.value,
            )],
            "all_paths": [list(path) for path in row.paths],
        })
        if not physical:
            missing.append(row.requirement_id)
    issues = (CoverageGap("broken_requirement_rflp_trace", "architecture", tuple(missing)),) if missing else ()
    return GateResult("P-Gate", not issues, issues, Phase.FUNCTIONAL if issues else None, tuple(checks))


def global_gate(graph: ModelGraph) -> GateResult:
    issues: list[CoverageGap] = []
    checks: list[dict[str, object]] = []
    if not _has(graph, EntityKind.VERIFICATION_CASE):
        issues.append(CoverageGap("missing_verification", "verification"))
    if not _has(graph, EntityKind.VALIDATION_CASE):
        issues.append(CoverageGap("missing_validation", "validation"))
    matrix = build_requirement_coverage(graph)
    for row in matrix.rows:
        linked = bool(row.verification_cases)
        checks.append({
            "id": f"requirement-verification:{row.requirement_id}",
            "passed": linked,
            "path": list((row.requirement_id, *row.verification_cases[:1])) if linked else [row.requirement_id],
            "missing_stage": "verification" if not linked else None,
            "expected_predicates": [item.value for item in sorted(R_TO_V.allowed_predicates, key=lambda item: item.value)],
        })
        if not linked:
            issues.append(CoverageGap("broken_requirement_verification_trace", "verification", (row.requirement_id,)))
        validation_linked = bool(row.validation_cases)
        checks.append({
            "id": f"requirement-validation:{row.requirement_id}",
            "passed": validation_linked,
            "path": list((row.requirement_id, *row.validation_cases[:1])) if validation_linked else [row.requirement_id],
            "missing_stage": "validation" if not validation_linked else None,
            "expected_predicates": [item.value for item in sorted(R_TO_VALIDATION.allowed_predicates, key=lambda item: item.value)],
        })
        if not validation_linked:
            issues.append(CoverageGap("broken_requirement_validation_trace", "validation", (row.requirement_id,)))
    return GateResult("Global-Gate", not issues, tuple(issues), Phase.ASSURANCE if issues else None, tuple(checks))


def _targets(graph: ModelGraph, source_id: str) -> tuple[str, ...]:
    return tuple(relation.target_id for relation in graph.relations if relation.source_id == source_id)


def gate_for_phase(phase: Phase, graph: ModelGraph) -> GateResult:
    if phase is Phase.OPERATIONAL:
        return operational_gate(graph)
    if phase is Phase.FUNCTIONAL:
        return functional_gate(graph)
    if phase is Phase.LOGICAL_PHYSICAL:
        return rflp_gate(graph)
    return global_gate(graph)
