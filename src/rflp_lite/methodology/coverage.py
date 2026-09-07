"""Coverage matrices used to route semantic gaps to the smallest repair."""

from __future__ import annotations

from dataclasses import dataclass

from rflp_lite.domain.entities import EntityKind, EntityStatus
from rflp_lite.domain.model import ModelGraph


@dataclass(frozen=True, slots=True)
class CoverageGap:
    code: str
    root_cause: str
    entity_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CoverageReport:
    gaps: tuple[CoverageGap, ...]
    covered_dimensions: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.gaps


def evaluate(graph: ModelGraph) -> CoverageReport:
    kinds = {entity.kind for entity in graph.entities if entity.meta.status is not EntityStatus.DEPRECATED}
    gaps: list[CoverageGap] = []
    if EntityKind.STAKEHOLDER not in kinds:
        gaps.append(CoverageGap("missing_stakeholder", "stakeholder"))
    if EntityKind.LIFECYCLE_STAGE not in kinds:
        gaps.append(CoverageGap("missing_lifecycle", "lifecycle"))
    if EntityKind.SCENARIO_HYPOTHESIS not in kinds and EntityKind.OPERATIONAL_SCENARIO not in kinds:
        gaps.append(CoverageGap("missing_scenario", "scenario"))
    if EntityKind.USE_CASE not in kinds:
        gaps.append(CoverageGap("missing_use_case", "scenario"))
    if EntityKind.REQUIREMENT not in kinds:
        gaps.append(CoverageGap("missing_requirement", "requirement"))
    if EntityKind.VERIFICATION_CASE not in kinds:
        gaps.append(CoverageGap("missing_verification", "verification"))
    return CoverageReport(tuple(gaps), tuple(sorted({"stakeholder", "lifecycle", "scenario", "requirement", "verification"} - {gap.root_cause for gap in gaps})))


def is_saturated(new_effective_evidence: tuple[int, ...], threshold: int = 0, rounds: int = 2) -> bool:
    return len(new_effective_evidence) >= rounds and all(value <= threshold for value in new_effective_evidence[-rounds:])
