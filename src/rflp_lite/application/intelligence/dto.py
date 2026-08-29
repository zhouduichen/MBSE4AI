"""Typed item DTOs for the schema-constrained LLM boundary."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Mapping

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import ContractViolation


def _text(value: object, field: str, *, required: bool = False) -> str:
    result = str(value or "").strip()
    if required and not result:
        raise ContractViolation(f"分析块 DTO 缺少 {field}")
    return result


def _texts(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _confidence(value: object) -> float:
    try:
        result = float(value if value is not None else 0.0)
    except (TypeError, ValueError) as exc:
        raise ContractViolation("分析块 DTO confidence 必须是数值") from exc
    if not math.isfinite(result):
        raise ContractViolation("分析块 DTO confidence 必须是有限数值")
    return max(0.0, min(1.0, result))


@dataclass(frozen=True, slots=True)
class StakeholderItem:
    id: str
    name: str
    category: str
    goals: tuple[str, ...]
    interactions: tuple[str, ...]
    source_region_ids: tuple[str, ...]
    confidence: float

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "StakeholderItem":
        return cls(
            _text(raw.get("id"), "id", required=True),
            _text(raw.get("name"), "name", required=True),
            _text(raw.get("category"), "category", required=True),
            _texts(raw.get("goals")),
            _texts(raw.get("interactions")),
            _texts(raw.get("source_region_ids")),
            _confidence(raw.get("confidence")),
        )


@dataclass(frozen=True, slots=True)
class RequirementItem:
    id: str
    subject: str
    predicate: str
    statement: str
    verification_method: str
    source_region_ids: tuple[str, ...]
    confidence: float

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "RequirementItem":
        return cls(
            _text(raw.get("id"), "id", required=True),
            _text(raw.get("subject"), "subject", required=True),
            _text(raw.get("predicate"), "predicate", required=True),
            _text(raw.get("statement"), "statement", required=True),
            _text(raw.get("verification_method"), "verification_method", required=True),
            _texts(raw.get("source_region_ids")),
            _confidence(raw.get("confidence")),
        )


@dataclass(frozen=True, slots=True)
class ScenarioItem:
    id: str
    title: str
    scenario_type: str
    actors: tuple[str, ...]
    steps: tuple[str, ...]
    expected_outcomes: tuple[str, ...]
    requirement_ids: tuple[str, ...]
    source_region_ids: tuple[str, ...]
    confidence: float

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "ScenarioItem":
        return cls(
            _text(raw.get("id"), "id", required=True),
            _text(raw.get("title"), "title", required=True),
            _text(raw.get("scenario_type"), "scenario_type", required=True),
            _texts(raw.get("actors")),
            _texts(raw.get("steps")),
            _texts(raw.get("expected_outcomes")),
            _texts(raw.get("requirement_ids")),
            _texts(raw.get("source_region_ids")),
            _confidence(raw.get("confidence")),
        )


@dataclass(frozen=True, slots=True)
class ArchitectureEntityItem:
    id: str
    kind: str
    name: str
    description: str
    requirement_ids: tuple[str, ...]
    source_region_ids: tuple[str, ...]
    confidence: float

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "ArchitectureEntityItem":
        return cls(
            _text(raw.get("id"), "id", required=True),
            _text(raw.get("kind"), "kind", required=True),
            _text(raw.get("name"), "name", required=True),
            _text(raw.get("description"), "description", required=True),
            _texts(raw.get("requirement_ids")),
            _texts(raw.get("source_region_ids")),
            _confidence(raw.get("confidence")),
        )


@dataclass(frozen=True, slots=True)
class ArchitectureRelationItem:
    id: str
    source_id: str
    predicate: str
    target_id: str
    requirement_ids: tuple[str, ...]
    source_region_ids: tuple[str, ...]
    confidence: float

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "ArchitectureRelationItem":
        return cls(
            _text(raw.get("id") or f"relation-{canonical_hash(raw)[:12]}", "id", required=True),
            _text(raw.get("source_id"), "source_id", required=True),
            _text(raw.get("predicate"), "predicate", required=True),
            _text(raw.get("target_id"), "target_id", required=True),
            _texts(raw.get("requirement_ids")),
            _texts(raw.get("source_region_ids")),
            _confidence(raw.get("confidence")),
        )


def typed_item(block_id: str, raw: Mapping[str, object]) -> object:
    if block_id == "stakeholders":
        return StakeholderItem.from_mapping(raw)
    if block_id == "requirements":
        return RequirementItem.from_mapping(raw)
    if block_id == "scenarios":
        return ScenarioItem.from_mapping(raw)
    if block_id == "architecture":
        if str(raw.get("kind", "")) == "relation":
            return ArchitectureRelationItem.from_mapping(raw)
        return ArchitectureEntityItem.from_mapping(raw)
    raise ContractViolation(f"分析块没有对应的 DTO: {block_id}")


def dto_to_dict(value: object) -> dict[str, object]:
    if not hasattr(value, "__dataclass_fields__"):
        raise TypeError("value must be a typed analysis DTO")
    return asdict(value)


__all__ = [
    "ArchitectureEntityItem",
    "ArchitectureRelationItem",
    "RequirementItem",
    "ScenarioItem",
    "StakeholderItem",
    "dto_to_dict",
    "typed_item",
]
