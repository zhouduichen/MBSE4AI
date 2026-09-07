"""Document identity used by the source-region ingestion port."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Artifact:
    id: str
    kind: str
    path: str
    sha256: str
