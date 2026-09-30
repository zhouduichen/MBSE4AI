"""Structured feedback emitted when a generated proposal fails validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ValidationFeedback:
    """A machine-readable correction request for the next generation attempt."""

    code: str
    affected_entities: tuple[str, ...] = ()
    expected: str = ""
    actual: str = ""
    failing_relation: Mapping[str, object] = field(default_factory=dict)
    evidence_gap: str = ""
    retry_count: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "affected_entities": list(self.affected_entities),
            "expected": self.expected,
            "actual": self.actual,
            "failing_relation": dict(self.failing_relation),
            "evidence_gap": self.evidence_gap,
            "retry_count": self.retry_count,
        }
