"""Deterministic requirement scope selection for downstream design workflows."""

from __future__ import annotations

from rflp_lite.domain.entities import EntityKind, EntityStatus
from rflp_lite.domain.model import ModelGraph


def root_requirement_ids(graph: ModelGraph) -> tuple[str, ...]:
    """Return active system-level requirements suitable as design sources.

    Technical requirements are derived artifacts and should not become an
    additional source of concept/CAD trace links when a user has not selected
    a narrower scope.  Explicit IDs supplied by a user remain authoritative.
    """

    return tuple(
        sorted(
            entity.id
            for entity in graph.entities
            if entity.kind is EntityKind.REQUIREMENT
            and entity.meta.status not in {EntityStatus.REJECTED, EntityStatus.DEPRECATED}
            and str(entity.payload.get("level", "system")).casefold() != "technical"
            and not entity.payload.get("source_requirement_ids")
        )
    )


__all__ = ["root_requirement_ids"]
