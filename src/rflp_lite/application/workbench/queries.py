"""Workbench query helpers kept separate from mutation orchestration."""

from __future__ import annotations

from pathlib import Path

from rflp_lite.application.workbench.snapshot import WorkbenchSnapshot
from rflp_lite.ports.repositories import WorkbenchRepositoryPort


def load_snapshot(
    repository: WorkbenchRepositoryPort, workspace: str | Path
) -> WorkbenchSnapshot | None:
    state = repository.load_workbench()
    if state is None:
        return None
    return WorkbenchSnapshot.from_state(str(workspace), state)
