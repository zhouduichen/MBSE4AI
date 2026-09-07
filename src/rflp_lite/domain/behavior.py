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

    @classmethod
    def create(
        cls,
        name: str,
        use_case_id: str,
        actor_ids: tuple[str, ...],
        exchanges: tuple[str, ...],
        steps: tuple[str, ...],
        *,
        revision: int = 0,
    ) -> "OperationalScenario":
        return cls(
            EntityMeta.create(EntityKind.OPERATIONAL_SCENARIO, name, revision=revision),
            use_case_id,
            tuple(actor_ids),
            tuple(exchanges),
            tuple(steps),
        )

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

    def as_entity(self) -> Entity:
        return Entity(self.meta, {
            "actor_ids": list(self.actor_ids),
            "requirement_ids": list(self.requirement_ids),
        })


@dataclass(frozen=True, slots=True)
class Activity:
    meta: EntityMeta
    predecessor_ids: tuple[str, ...] = ()
    requirement_ids: tuple[str, ...] = ()

    def as_entity(self) -> Entity:
        return Entity(self.meta, {
            "predecessor_ids": list(self.predecessor_ids),
            "requirement_ids": list(self.requirement_ids),
        })


@dataclass(frozen=True, slots=True)
class Function:
    meta: EntityMeta
    purpose: str = ""
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()

    def as_entity(self) -> Entity:
        return Entity(self.meta, {"purpose": self.purpose, "inputs": list(self.inputs), "outputs": list(self.outputs)})


@dataclass(frozen=True, slots=True)
class FunctionalFlow:
    meta: EntityMeta
    source_function_id: str
    target_function_id: str
    item: str = ""

    def as_entity(self) -> Entity:
        return Entity(self.meta, {"source_function_id": self.source_function_id, "target_function_id": self.target_function_id, "item": self.item})


@dataclass(frozen=True, slots=True)
class FunctionalScenario:
    meta: EntityMeta
    function_ids: tuple[str, ...] = ()

    def as_entity(self) -> Entity:
        return Entity(self.meta, {"function_ids": list(self.function_ids)})


@dataclass(frozen=True, slots=True)
class LogicalComponent:
    meta: EntityMeta
    responsibility: str = ""

    def as_entity(self) -> Entity:
        return Entity(self.meta, {"responsibility": self.responsibility})


@dataclass(frozen=True, slots=True)
class PhysicalBlock:
    meta: EntityMeta
    candidate: bool = True
    tradeoff: Mapping[str, object] = ()

    def as_entity(self) -> Entity:
        return Entity(self.meta, {"candidate": self.candidate, "tradeoff": dict(self.tradeoff)})


@dataclass(frozen=True, slots=True)
class Interface:
    meta: EntityMeta
    source_id: str
    target_id: str
    exchanged_items: tuple[str, ...] = ()

    def as_entity(self) -> Entity:
        return Entity(self.meta, {"source_id": self.source_id, "target_id": self.target_id, "exchanged_items": list(self.exchanged_items)})


@dataclass(frozen=True, slots=True)
class State:
    meta: EntityMeta
    entry_condition: str = ""
    exit_condition: str = ""

    def as_entity(self) -> Entity:
        return Entity(self.meta, {"entry_condition": self.entry_condition, "exit_condition": self.exit_condition})


@dataclass(frozen=True, slots=True)
class Hazard:
    meta: EntityMeta
    cause: str = ""
    consequence: str = ""

    def as_entity(self) -> Entity:
        return Entity(self.meta, {"cause": self.cause, "consequence": self.consequence})


@dataclass(frozen=True, slots=True)
class FailureMode:
    meta: EntityMeta
    effect: str = ""
    detection: str = ""

    def as_entity(self) -> Entity:
        return Entity(self.meta, {"effect": self.effect, "detection": self.detection})


@dataclass(frozen=True, slots=True)
class VerificationCase:
    meta: EntityMeta
    method: str
    expected_result: str = ""

    def as_entity(self) -> Entity:
        return Entity(self.meta, {"method": self.method, "expected_result": self.expected_result})


@dataclass(frozen=True, slots=True)
class ValidationCase:
    meta: EntityMeta
    scenario_id: str
    expected_outcome: str = ""

    def as_entity(self) -> Entity:
        return Entity(self.meta, {"scenario_id": self.scenario_id, "expected_outcome": self.expected_outcome})


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
