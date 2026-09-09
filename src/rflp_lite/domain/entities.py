"""Typed entities shared by the v2 Model Graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping

from rflp_lite.domain.canonical import canonical_hash, canonical_json


class EntityKind(StrEnum):
    SYSTEM = "system"
    STAKEHOLDER = "stakeholder"
    CONCERN = "concern"
    LIFECYCLE_STAGE = "lifecycle_stage"
    LIFECYCLE_TRANSITION = "lifecycle_transition"
    SCENARIO_HYPOTHESIS = "scenario_hypothesis"
    USE_CASE = "use_case"
    OPERATIONAL_SCENARIO = "operational_scenario"
    ACTIVITY = "activity"
    REQUIREMENT = "requirement"
    FUNCTION = "function"
    FUNCTIONAL_FLOW = "functional_flow"
    FUNCTIONAL_SCENARIO = "functional_scenario"
    LOGICAL_COMPONENT = "logical_component"
    PHYSICAL_BLOCK = "physical_block"
    INTERFACE = "interface"
    STATE = "state"
    HAZARD = "hazard"
    FAILURE_MODE = "failure_mode"
    VERIFICATION_CASE = "verification_case"
    VALIDATION_CASE = "validation_case"
    EVIDENCE = "evidence"


class EntityStatus(StrEnum):
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEPRECATED = "deprecated"
    LOCKED = "locked"


class Producer(StrEnum):
    USER = "user"
    LLM = "llm"
    RULE = "rule"
    IMPORT = "import"


@dataclass(frozen=True, slots=True)
class EntityMeta:
    id: str
    kind: EntityKind
    name: str
    status: EntityStatus = EntityStatus.CANDIDATE
    producer: Producer = Producer.RULE
    confidence: float | None = None
    source_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    lifecycle_ids: tuple[str, ...] = ()
    created_revision: int = 0
    updated_revision: int = 0

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("entity id is required")
        if not self.name.strip():
            raise ValueError("entity name is required")
        if self.confidence is not None and not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.created_revision < 0 or self.updated_revision < 0:
            raise ValueError("revision cannot be negative")

    @classmethod
    def create(
        cls,
        kind: EntityKind,
        name: str,
        *,
        status: EntityStatus = EntityStatus.CANDIDATE,
        producer: Producer = Producer.RULE,
        confidence: float | None = None,
        source_ids: tuple[str, ...] = (),
        evidence_ids: tuple[str, ...] = (),
        lifecycle_ids: tuple[str, ...] = (),
        revision: int = 0,
    ) -> "EntityMeta":
        clean_name = str(name).strip()
        identity = (kind.value, clean_name, tuple(source_ids), tuple(lifecycle_ids))
        return cls(
            id=f"{kind.value}-{canonical_hash(identity)[:16]}",
            kind=kind,
            name=clean_name,
            status=status,
            producer=producer,
            confidence=confidence,
            source_ids=tuple(dict.fromkeys(str(value) for value in source_ids if str(value))),
            evidence_ids=tuple(dict.fromkeys(str(value) for value in evidence_ids if str(value))),
            lifecycle_ids=tuple(dict.fromkeys(str(value) for value in lifecycle_ids if str(value))),
            created_revision=revision,
            updated_revision=revision,
        )


@dataclass(frozen=True, slots=True)
class Entity:
    """A typed graph node with an intentionally bounded payload."""

    meta: EntityMeta
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.payload, Mapping):
            raise TypeError("entity payload must be a mapping")

    @property
    def id(self) -> str:
        return self.meta.id

    @property
    def kind(self) -> EntityKind:
        return self.meta.kind

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.meta.id,
            "kind": self.meta.kind.value,
            "name": self.meta.name,
            "status": self.meta.status.value,
            "producer": self.meta.producer.value,
            "confidence": self.meta.confidence,
            "source_ids": list(self.meta.source_ids),
            "evidence_ids": list(self.meta.evidence_ids),
            "lifecycle_ids": list(self.meta.lifecycle_ids),
            "created_revision": self.meta.created_revision,
            "updated_revision": self.meta.updated_revision,
            "payload": dict(self.payload),
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.as_dict())


def make_entity(
    kind: EntityKind,
    name: str,
    payload: Mapping[str, object] | None = None,
    **meta: object,
) -> Entity:
    """Create a graph node while keeping identity construction in one place."""

    return Entity(
        EntityMeta.create(kind, name, **meta),
        dict(payload or {}),
    )


def entity_json(entity: Entity) -> str:
    return canonical_json(entity.as_dict())
