"""Stable value objects shared by retrieval implementations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EvidenceCandidate:
    id: str
    source_type: str
    source_id: str
    locator: str
    claim: str
    excerpt: str
    confidence: float = 0.5
