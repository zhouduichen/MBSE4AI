"""Stable tracking records shared by application code and tracking adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TrackingRecord:
    """Read-only run record exposed to optional tracking implementations."""

    result_hash: str
    run_dir: Path
    manifest: dict[str, object]
    outputs: dict[str, object]
    modified_ns: int
