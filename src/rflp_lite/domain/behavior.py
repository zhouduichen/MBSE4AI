"""Typed behavior and architecture entities for the v2 model graph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from rflp_lite.domain.entities import Entity, EntityKind, EntityMeta


@dataclass(frozen=True, slots=True)
class ScenarioHypothesis:
    meta: EntityMeta
    goal: str
    trigger: str
    preconditions: tuple[str, ...] = ()
    environment: tuple[str, ...] = ()
    paths: Mapping[str, tuple[str, ...]] = ()
    stakeholder_ids: tuple[str, ...] = ()

    @classmethod
    def create(cls, name: str, goal: str, trigger: str) -> "ScenarioHypothesis":
        return cls(
            EntityMeta.create(EntityKind.SCENARIO_HYPOTHESIS, name),
            goal.strip(), trigger.strip(),
        )

    def as_entity(self) -> Entity:
        return Entity(self.meta, {
            "goal": self.goal,
            "trigger": self.trigger,
            "preconditions": list(self.preconditions),
            "environment": list(self.environment),
            "paths": {key: list(value) for key, value in self.paths.items()},
            "stakeholder_ids": list(self.stakeholder_ids),
        })


@dataclass(frozen=True, slots=True)
class OperationalScenario:
    meta: EntityMeta
    use_case_id: str
    actor_ids: tuple[str, ...]
    exchanges: tuple[str, ...]
    steps: tuple[str, ...]
    precondition: str = ""
    postcondition: str = ""
    exception_paths: tuple[str, ...] = ()

    def as_entity(self) -> Entity:
        return Entity(self.meta, {
            "use_case_id": self.use_case_id,
            "actor_ids": list(self.actor_ids),
            "exchanges": list(self.exchanges),
            "steps": list(self.steps),
            "precondition": self.precondition,
            "postcondition": self.postcondition,
            "exception_paths": list(self.exception_paths),
        })


@dataclass(frozen=True, slots=True)
class UseCase:
    meta: EntityMeta
    actor_ids: tuple[str, ...]
    requirement_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Activity:
    meta: EntityMeta
    predecessor_ids: tuple[str, ...] = ()
    requirement_ids: tuple[str, ...] = ()


def architecture_entity(kind: EntityKind, name: str, payload: Mapping[str, object]) -> Entity:
    if kind not in {
        EntityKind.FUNCTION,
        EntityKind.FUNCTIONAL_FLOW,
        EntityKind.FUNCTIONAL_SCENARIO,
        EntityKind.LOGICAL_COMPONENT,
        EntityKind.PHYSICAL_BLOCK,
        EntityKind.INTERFACE,
    }:
        raise ValueError(f"not an architecture kind: {kind.value}")
    return Entity(EntityMeta.create(kind, name), dict(payload))
