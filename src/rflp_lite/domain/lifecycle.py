"""Lifecycle value objects used by Operational and Assurance stages."""

from __future__ import annotations

from dataclasses import dataclass

from rflp_lite.domain.entities import Entity, EntityKind, EntityMeta


@dataclass(frozen=True, slots=True)
class LifecycleStage:
    meta: EntityMeta
    purpose: str = ""
    entry_criteria: tuple[str, ...] = ()
    exit_criteria: tuple[str, ...] = ()

    @classmethod
    def create(cls, name: str, *, purpose: str = "", revision: int = 0) -> "LifecycleStage":
        return cls(
            EntityMeta.create(EntityKind.LIFECYCLE_STAGE, name, revision=revision),
            purpose.strip(),
        )

    def as_entity(self) -> Entity:
        return Entity(
            self.meta,
            {
                "purpose": self.purpose,
                "entry_criteria": list(self.entry_criteria),
                "exit_criteria": list(self.exit_criteria),
            },
        )


@dataclass(frozen=True, slots=True)
class LifecycleTransition:
    id: str
    source_stage_id: str
    target_stage_id: str
    trigger: str
    guard: str = ""

