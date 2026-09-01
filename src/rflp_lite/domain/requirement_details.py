"""Structured details attached to a requirement candidate.

The detail records deliberately keep source evidence and review state in the
domain layer.  They are immutable, JSON-friendly contracts that can be
created by deterministic extraction as well as by a future model-assisted
extractor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from rflp_lite.domain.canonical import canonical_hash


def _texts(values: Iterable[object]) -> tuple[str, ...]:
    """Normalize text values while preserving their first-seen order."""

    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return tuple(result)


def _confidence(value: object) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence must be a number") from exc
    if not math.isfinite(result):
        raise ValueError("confidence must be finite")
    return max(0.0, min(1.0, result))


def _required_text(value: object, field: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


@dataclass(frozen=True, slots=True)
class RequirementAttribute:
    """A typed value, range, or enumeration extracted for a requirement."""

    id: str
    requirement_id: str
    name: str
    value: str
    unit: str
    minimum: str
    maximum: str
    enum_values: tuple[str, ...]
    source_region_ids: tuple[str, ...]
    confidence: float
    status: str = "candidate"
    producer: str = "rule"

    @classmethod
    def from_fields(
        cls,
        *,
        requirement_id: str,
        name: str,
        value: str = "",
        unit: str = "",
        minimum: str = "",
        maximum: str = "",
        enum_values: tuple[str, ...] = (),
        source_region_ids: tuple[str, ...],
        confidence: float = 1.0,
        status: str = "candidate",
        producer: str = "rule",
    ) -> "RequirementAttribute":
        requirement = _required_text(requirement_id, "requirement_id")
        attribute_name = _required_text(name, "name")
        sources = _texts(source_region_ids)
        if not sources:
            raise ValueError("source_region_ids is required")
        normalized_value = str(value).strip()
        normalized_unit = str(unit).strip()
        normalized_minimum = str(minimum).strip()
        normalized_maximum = str(maximum).strip()
        normalized_enum_values = _texts(enum_values)
        identity = (
            requirement,
            attribute_name,
            normalized_value,
            normalized_unit,
            normalized_minimum,
            normalized_maximum,
            normalized_enum_values,
            sources,
        )
        return cls(
            id=f"attribute-{canonical_hash(identity)[:12]}",
            requirement_id=requirement,
            name=attribute_name,
            value=normalized_value,
            unit=normalized_unit,
            minimum=normalized_minimum,
            maximum=normalized_maximum,
            enum_values=normalized_enum_values,
            source_region_ids=sources,
            confidence=_confidence(confidence),
            status=str(status).strip() or "candidate",
            producer=str(producer).strip() or "rule",
        )


@dataclass(frozen=True, slots=True)
class RequirementConstraint:
    """A reviewable explicit or inferred constraint over requirements."""

    id: str
    requirement_ids: tuple[str, ...]
    constraint_type: str
    expression: str
    explicitness: str
    source_region_ids: tuple[str, ...]
    rationale: str
    verification_method: str
    confidence: float
    status: str = "candidate"
    producer: str = "rule"

    @classmethod
    def from_fields(
        cls,
        *,
        requirement_ids: tuple[str, ...],
        constraint_type: str,
        expression: str,
        explicitness: str,
        source_region_ids: tuple[str, ...],
        rationale: str = "",
        verification_method: str = "review",
        confidence: float = 1.0,
        status: str = "candidate",
        producer: str = "rule",
    ) -> "RequirementConstraint":
        requirements = tuple(sorted(_texts(requirement_ids)))
        if not requirements:
            raise ValueError("requirement_ids is required")
        sources = _texts(source_region_ids)
        if not sources:
            raise ValueError("source_region_ids is required")
        normalized_type = _required_text(constraint_type, "constraint_type")
        normalized_expression = _required_text(expression, "expression")
        normalized_explicitness = str(explicitness).strip()
        if normalized_explicitness not in {"explicit", "inferred"}:
            raise ValueError("explicitness must be explicit or inferred")
        identity = (
            requirements,
            normalized_type,
            normalized_expression,
            normalized_explicitness,
            sources,
        )
        return cls(
            id=f"constraint-{canonical_hash(identity)[:12]}",
            requirement_ids=requirements,
            constraint_type=normalized_type,
            expression=normalized_expression,
            explicitness=normalized_explicitness,
            source_region_ids=sources,
            rationale=str(rationale).strip(),
            verification_method=str(verification_method).strip() or "review",
            confidence=_confidence(confidence),
            status=str(status).strip() or "candidate",
            producer=str(producer).strip() or "rule",
        )


__all__ = ["RequirementAttribute", "RequirementConstraint"]
