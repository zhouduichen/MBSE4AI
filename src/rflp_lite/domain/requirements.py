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
    source_region_id: str
    subject: str
    predicate: str
    statement: str
    source_type: str
    entities: tuple[str, ...]
    constraints: tuple[tuple[str, str], ...]
    verification_method: str
    confidence: float = 1.0
    status: str = "candidate"
    producer: str = "rule"
    priority: str = "unassigned"
    verification_metric: str = ""
    rationale: str = ""

    @classmethod
    def from_fields(
        cls,
        *,
        region: object | None = None,
        source_region_id: str = "",
        source_region_ids: tuple[str, ...] = (),
        subject: str,
        predicate: str,
        statement: str = "",
        object: str = "",
        source_type: str = "explicit",
        entities: tuple[str, ...] = (),
        constraints: tuple[tuple[str, str], ...] = (),
        verification_method: str = "review",
        confidence: float = 1.0,
        status: str = "candidate",
        producer: str = "rule",
        priority: str = "unassigned",
        verification_metric: str = "",
        rationale: str = "",
    ) -> "StructuredRequirement":
        if region is not None:
            source_region_id = str(getattr(region, "id", ""))
        if not source_region_id and source_region_ids:
            source_region_id = str(source_region_ids[0])
        if not source_region_id:
            raise ValueError("source_region_id is required")
        statement = statement or object
        identity = {
            "source_region_id": source_region_id,
            "subject": subject.strip(),
            "predicate": predicate.strip(),
            "statement": statement.strip(),
            "source_type": source_type.strip() or "explicit",
            "entities": entities,
            "constraints": constraints,
        }
        return cls(
            id=f"requirement-{canonical_hash(identity)[:12]}",
            source_region_id=identity["source_region_id"],
            subject=identity["subject"],
            predicate=identity["predicate"],
            statement=identity["statement"],
            source_type=identity["source_type"],
            entities=tuple(str(value) for value in identity["entities"]),
            constraints=tuple((str(key), str(value)) for key, value in identity["constraints"]),
            verification_method=verification_method.strip() or "review",
            confidence=max(0.0, min(1.0, float(confidence))),
            status=status.strip() or "candidate",
            producer=producer.strip() or "rule",
            priority=priority.strip() or "unassigned",
            verification_metric=verification_metric.strip(),
            rationale=rationale.strip(),
        )

    @property
    def source_region_ids(self) -> tuple[str, ...]:
        return (self.source_region_id,)

    @property
    def object(self) -> str:
        return self.statement


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
