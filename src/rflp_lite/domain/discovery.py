from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping

from rflp_lite.domain.canonical import canonical_hash, canonical_json


SOURCE_TYPES = frozenset({"explicit", "derived", "inferred", "assumed", "external_reference"})
REVIEW_STATUSES = frozenset({"candidate", "accepted", "rejected", "stale"})
COVERAGE_STATUSES = frozenset({"covered", "candidate", "unknown", "not_applicable"})


@dataclass(frozen=True, slots=True)
class ProvenanceRef:
    source_type: str
    source_id: str
    rationale: str = ""

    def __post_init__(self) -> None:
        if self.source_type not in SOURCE_TYPES:
            raise ValueError("invalid source_type")
        if not self.source_id.strip():
            raise ValueError("source_id is required")


@dataclass(frozen=True, slots=True)
class CandidateEnvelope:
    id: str
    element_type: str
    schema_version: int
    pack_id: str
    status: str
    payload_json: str
    provenance: tuple[ProvenanceRef, ...]
    assumptions: tuple[str, ...]
    confidence: float
    producer: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        element_type: str,
        pack_id: str,
        payload: Mapping[str, object],
        provenance: tuple[ProvenanceRef, ...],
        producer: str,
        assumptions: tuple[str, ...] = (),
        confidence: float = 1.0,
        schema_version: int = 1,
        status: str = "candidate",
    ) -> "CandidateEnvelope":
        if not element_type.strip() or not pack_id.strip() or not producer.strip():
            raise ValueError("element_type, pack_id and producer are required")
        if not provenance:
            raise ValueError("provenance is required")
        if status not in REVIEW_STATUSES:
            raise ValueError("invalid status")
        if not 0.0 <= float(confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        normalized_payload = json.loads(canonical_json(dict(payload)))
        content_hash = canonical_hash((element_type, normalized_payload))
        identity = (
            pack_id,
            element_type,
            normalized_payload,
            tuple((item.source_type, item.source_id) for item in provenance),
        )
        return cls(
            id=f"candidate-{canonical_hash(identity)[:16]}",
            element_type=element_type,
            schema_version=int(schema_version),
            pack_id=pack_id,
            status=status,
            payload_json=canonical_json(normalized_payload),
            provenance=provenance,
            assumptions=tuple(str(item) for item in assumptions),
            confidence=float(confidence),
            producer=producer,
            content_hash=content_hash,
        )

    @property
    def payload(self) -> dict[str, object]:
        return json.loads(self.payload_json)

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "element_type": self.element_type,
            "schema_version": self.schema_version,
            "pack_id": self.pack_id,
            "status": self.status,
            "payload": self.payload,
            "provenance": [
                {
                    "source_type": item.source_type,
                    "source_id": item.source_id,
                    "rationale": item.rationale,
                }
                for item in self.provenance
            ],
            "assumptions": list(self.assumptions),
            "confidence": self.confidence,
            "producer": self.producer,
            "content_hash": self.content_hash,
        }
