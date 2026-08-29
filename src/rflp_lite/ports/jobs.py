"""Durable job service contracts."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    DEGRADED = "degraded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"


ACTIVE_JOB_STATUSES = frozenset({JobStatus.QUEUED.value, JobStatus.RUNNING.value})
TERMINAL_JOB_STATUSES = frozenset(
    {
        JobStatus.SUCCEEDED.value,
        JobStatus.DEGRADED.value,
        JobStatus.FAILED.value,
        JobStatus.INTERRUPTED.value,
        JobStatus.SUPERSEDED.value,
        JobStatus.CANCELLED.value,
    }
)


class JobRepositoryPort(Protocol):
    def submit(self, kind: str, payload: dict[str, object]) -> dict[str, object]: ...

    def update(self, job_id: str, patch: dict[str, object]) -> dict[str, object] | None: ...

    def get(self, job_id: str) -> dict[str, object] | None: ...

    def list(self) -> tuple[dict[str, object], ...]: ...

    def recover_startup(self, now: float | None = None) -> tuple[dict[str, object], ...]: ...

    def heartbeat(
        self, job_id: str, lease_id: str, now: float | None = None
    ) -> dict[str, object] | None: ...

    def import_legacy_file(self, source: Path, archived: Path) -> int: ...


class BackgroundExecutorPort(Protocol):
    def submit(self, job_id: str, runner: Callable[[], None]) -> None: ...


JobServiceFactory = Callable[[Path], JobRepositoryPort]
