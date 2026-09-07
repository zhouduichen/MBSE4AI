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
    issues = () if _has(graph, *required) else (CoverageGap("incomplete_rflp_chain", "architecture"),)
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
