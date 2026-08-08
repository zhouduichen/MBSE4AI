"""Small semantic MBSE value objects used by the modeling service."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Actor:
    id: str
    name: str
    requirement_ids: tuple[str, ...] = ()
    status: str = "candidate"


@dataclass(frozen=True, slots=True)
class UseCase:
    id: str
    name: str
    actor_ids: tuple[str, ...]
    requirement_ids: tuple[str, ...]
    status: str = "candidate"


@dataclass(frozen=True, slots=True)
class Activity:
    id: str
    name: str
    kind: str
    predecessor_ids: tuple[str, ...]
    requirement_ids: tuple[str, ...]
    status: str = "candidate"


@dataclass(frozen=True, slots=True)
class Lifeline:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class Message:
    id: str
    name: str
    from_id: str
    to_id: str
    sequence: int
    requirement_ids: tuple[str, ...]
    status: str = "candidate"

