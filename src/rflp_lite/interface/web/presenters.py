from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rflp_lite.application.run_catalog import RunRecord
from rflp_lite.application.workspaces import WorkspaceRef


def short_hash(value: object, length: int = 12) -> str:
    text = str(value or "")
    return text if len(text) <= length else f"{text[:length]}…"


def page_context(
    workspace: WorkspaceRef | None,
    *,
    workspaces: tuple[WorkspaceRef, ...] = (),
    active: str = "dashboard",
    **values: Any,
) -> dict[str, object]:
    return {
        "workspace": workspace,
        "workspaces": workspaces,
        "active": active,
        "short_hash": short_hash,
        **values,
    }


def run_detail_context(workspace: WorkspaceRef, record: RunRecord) -> dict[str, object]:
    return page_context(
        workspace,
        active="runs",
        run=record,
        manifest=record.outputs["run-manifest.json"],
        decision=record.outputs["decision.json"],
        simulation=record.outputs["simulation.json"],
        baseline=record.outputs["baseline.json"],
        files=tuple(record.outputs),
    )


@dataclass(frozen=True, slots=True)
class Capability:
    name: str
    status: str
    purpose: str
    dependency: str
    expected_input: str
    expected_output: str
    enable_when: str
