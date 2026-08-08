"""Versioned domain contracts for customer-facing requirements engineering.

These records deliberately keep provenance and review state explicit.  They are
small enough to serialize to JSON while remaining useful to the web, CLI and
future MBSE adapters.
"""

from __future__ import annotations

from dataclasses import dataclass

from rflp_lite.domain.canonical import canonical_hash


@dataclass(frozen=True, slots=True)
class DocumentRegion:
    id: str
    artifact_id: str
    page: int | None
    kind: str
    locator: str
    text: str
    bbox: tuple[float, float, float, float] = ()
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class StructuredRequirement:
    id: str
    source_region_ids: tuple[str, ...]
    subject: str
    predicate: str
    object: str
    modality: str
    priority: str
    verification_method: str
    verification_metric: str
    rationale: str
    source_type: str = "explicit"
    confidence: float = 1.0
    status: str = "candidate"

    @classmethod
    def from_fields(
        cls,
        *,
        source_region_ids: tuple[str, ...],
        subject: str,
        predicate: str,
        object: str,
        modality: str = "shall",
        priority: str = "unassigned",
        verification_method: str = "review",
        verification_metric: str = "",
        rationale: str = "",
        source_type: str = "explicit",
        confidence: float = 1.0,
        status: str = "candidate",
    ) -> "StructuredRequirement":
        identity = {
            "source_region_ids": source_region_ids,
            "subject": subject.strip(),
            "predicate": predicate.strip(),
            "object": object.strip(),
            "modality": modality.strip(),
        }
        return cls(
            id=f"REQ-{canonical_hash(identity)[:12]}",
            source_region_ids=source_region_ids,
            subject=identity["subject"],
            predicate=identity["predicate"],
            object=identity["object"],
            modality=identity["modality"],
            priority=priority.strip() or "unassigned",
            verification_method=verification_method.strip() or "review",
            verification_metric=verification_metric.strip(),
            rationale=rationale.strip(),
            source_type=source_type.strip() or "explicit",
            confidence=max(0.0, min(1.0, float(confidence))),
            status=status.strip() or "candidate",
        )


@dataclass(frozen=True, slots=True)
class TraceLink:
    id: str
    source_id: str
    predicate: str
    target_id: str
    producer: str
    status: str = "candidate"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    id: str
    scope: str
    code: str
    message: str
    source_id: str = ""
    severity: str = "warning"

