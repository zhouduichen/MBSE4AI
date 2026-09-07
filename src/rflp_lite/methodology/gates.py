"""Deterministic Phase Gates; semantic critics can add diagnostics later."""

from __future__ import annotations

from dataclasses import dataclass

from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.contracts import Phase
from rflp_lite.methodology.coverage import CoverageGap, CoverageReport, evaluate


@dataclass(frozen=True, slots=True)
class GateResult:
    gate_id: str
    passed: bool
    issues: tuple[CoverageGap, ...] = ()
    rollback_phase: Phase | None = None


def _has(graph: ModelGraph, *kinds: EntityKind) -> bool:
    present = {entity.kind for entity in graph.entities}
    return all(kind in present for kind in kinds)


def operational_gate(graph: ModelGraph) -> GateResult:
    report = evaluate(graph)
    issues = tuple(gap for gap in report.gaps if gap.root_cause in {"stakeholder", "lifecycle", "scenario", "requirement"})
    return GateResult("O-Gate", not issues, issues, Phase.OPERATIONAL if issues else None)


def functional_gate(graph: ModelGraph) -> GateResult:
    issues = () if _has(graph, EntityKind.FUNCTION) else (CoverageGap("missing_function", "function"),)
    return GateResult("F-Gate", not issues, issues, Phase.FUNCTIONAL if issues else None)


def rflp_gate(graph: ModelGraph) -> GateResult:
    required = (EntityKind.REQUIREMENT, EntityKind.FUNCTION, EntityKind.LOGICAL_COMPONENT, EntityKind.PHYSICAL_BLOCK)
    if not _has(graph, *required):
        return GateResult("P-Gate", False, (CoverageGap("incomplete_rflp_chain", "architecture"),), Phase.FUNCTIONAL)
    index = graph.entity_index
    accepted_requirements = {
        entity.id for entity in graph.entities
        if entity.kind is EntityKind.REQUIREMENT and entity.meta.status.value == "accepted"
    }
    if not accepted_requirements:
        return GateResult("P-Gate", True)
    by_source: dict[str, set[str]] = {}
    for relation in graph.relations:
        by_source.setdefault(relation.source_id, set()).add(relation.target_id)
    missing = []
    for requirement_id in sorted(accepted_requirements):
        functions = {target for target in by_source.get(requirement_id, set()) if index.get(target) and index[target].kind is EntityKind.FUNCTION}
        logical = {target for function_id in functions for target in by_source.get(function_id, set()) if index.get(target) and index[target].kind is EntityKind.LOGICAL_COMPONENT}
        physical = {target for logical_id in logical for target in by_source.get(logical_id, set()) if index.get(target) and index[target].kind is EntityKind.PHYSICAL_BLOCK}
        if not physical:
            missing.append(requirement_id)
    issues = (CoverageGap("broken_requirement_rflp_trace", "architecture", tuple(missing)),) if missing else ()
    return GateResult("P-Gate", not issues, issues, Phase.FUNCTIONAL if issues else None)


def global_gate(graph: ModelGraph) -> GateResult:
    issues = () if _has(graph, EntityKind.VERIFICATION_CASE) else (CoverageGap("missing_verification", "verification"),)
    return GateResult("Global-Gate", not issues, issues, Phase.ASSURANCE if issues else None)


def gate_for_phase(phase: Phase, graph: ModelGraph) -> GateResult:
    if phase is Phase.OPERATIONAL:
        return operational_gate(graph)
    if phase is Phase.FUNCTIONAL:
        return functional_gate(graph)
    if phase is Phase.LOGICAL_PHYSICAL:
        return rflp_gate(graph)
    return global_gate(graph)
