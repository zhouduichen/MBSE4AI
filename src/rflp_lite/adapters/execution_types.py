from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rflp_lite.domain.models import Evidence


@dataclass(frozen=True, slots=True)
class RunnerResult:
    runner: str
    command: tuple[str, ...]
    returncode: int | None
    timed_out: bool
    junit_path: Path | None
    stdout_path: Path | None
    stderr_path: Path | None
    temp_dir: Path | None
    evidence: tuple[Evidence, ...]
    diagnostics: dict[str, object]
    resource_limits: dict[str, object]
    cache_hit: bool = False
