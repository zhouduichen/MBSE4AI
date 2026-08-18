"""Durable job service contracts."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol


JobRunner = Callable[[], dict[str, object]]


class JobRepositoryPort(Protocol):
    def submit_async(
        self, kind: str, payload: dict[str, object], runner: JobRunner
    ) -> dict[str, object]: ...

    def update(self, job_id: str, patch: dict[str, object]) -> dict[str, object] | None: ...

    def get(self, job_id: str) -> dict[str, object] | None: ...

    def list(self) -> tuple[dict[str, object], ...]: ...


JobServiceFactory = Callable[[Path], JobRepositoryPort]
