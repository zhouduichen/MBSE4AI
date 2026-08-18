"""Ports for read-only project analysis and bounded test execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class ProjectScannerPort(Protocol):
    def scan(self, root: Path) -> tuple[Any, dict[str, object]]: ...


class TestExecutionPort(Protocol):
    def run(
        self,
        project_dir: Path,
        *,
        runners: tuple[str, ...],
        limits: object | None,
        cache_dir: Path | None,
        jobs: int,
    ) -> tuple[Any, ...]: ...
