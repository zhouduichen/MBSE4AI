"""Stable view definitions for ModelGraph projections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from rflp_lite.domain.entities import EntityKind


@dataclass(frozen=True, slots=True)
class ViewSpec:
    view_id: str
    title: str
    source_graph_hash: str
    nodes: tuple[Mapping[str, object], ...]
    edges: tuple[Mapping[str, object], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "view_id": self.view_id,
            "title": self.title,
            "source_graph_hash": self.source_graph_hash,
            "nodes": [dict(node) for node in self.nodes],
            "edges": [dict(edge) for edge in self.edges],
        }


_VIEW_KINDS: dict[str, frozenset[EntityKind]] = {
    "operational": frozenset({
        EntityKind.SYSTEM, EntityKind.STAKEHOLDER, EntityKind.CONCERN,
        EntityKind.LIFECYCLE_STAGE, EntityKind.LIFECYCLE_TRANSITION,
        EntityKind.SCENARIO_HYPOTHESIS, EntityKind.USE_CASE,
        EntityKind.OPERATIONAL_SCENARIO, EntityKind.ACTIVITY,
    }),
    "functional": frozenset({
        EntityKind.REQUIREMENT, EntityKind.FUNCTION, EntityKind.FUNCTIONAL_FLOW,
        EntityKind.FUNCTIONAL_SCENARIO,
    }),
    "logical": frozenset({EntityKind.FUNCTION, EntityKind.LOGICAL_COMPONENT, EntityKind.INTERFACE}),
    "physical": frozenset({EntityKind.LOGICAL_COMPONENT, EntityKind.PHYSICAL_BLOCK, EntityKind.INTERFACE}),
    "assurance": frozenset({
        EntityKind.REQUIREMENT, EntityKind.INTERFACE, EntityKind.STATE,
        EntityKind.HAZARD, EntityKind.FAILURE_MODE, EntityKind.VERIFICATION_CASE,
        EntityKind.VALIDATION_CASE,
    }),
    "traceability": frozenset({EntityKind.REQUIREMENT, EntityKind.FUNCTION, EntityKind.LOGICAL_COMPONENT, EntityKind.PHYSICAL_BLOCK, EntityKind.VERIFICATION_CASE}),
    "evidence": frozenset({EntityKind.EVIDENCE}),
}


def view_ids() -> tuple[str, ...]:
    return tuple(_VIEW_KINDS) + ("rflp",)


def kinds_for_view(view_id: str) -> frozenset[EntityKind] | None:
    if view_id == "rflp":
        return frozenset({
            EntityKind.REQUIREMENT, EntityKind.FUNCTION, EntityKind.LOGICAL_COMPONENT,
            EntityKind.PHYSICAL_BLOCK,
        })
    if view_id == "all":
        return None
    try:
        return _VIEW_KINDS[view_id]
    except KeyError as exc:
        raise ValueError(f"unsupported ModelGraph view: {view_id}") from exc
