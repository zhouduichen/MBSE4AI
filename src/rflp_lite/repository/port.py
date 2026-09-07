"""Persistence ports for the typed Model Graph and Run Ledger."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from rflp_lite.domain.entities import Entity, EntityKind
from rflp_lite.domain.model import ModelGraph, Patch, Revision


@dataclass(frozen=True, slots=True)
class Step:
    run_id: str
    task_id: str
    status: str = "queued"
    attempt: int = 0
    input_hash: str = ""
    output_patch_id: str | None = None
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Run:
    id: str
    project_id: str
    phase: str
    status: str = "queued"
    attempt: int = 0
    methodology_version: str = "v2.0"
    model_profile: str = ""
    input_hash: str = ""
    diagnostics: tuple[str, ...] = ()
    steps: tuple[Step, ...] = ()


class ModelRepository(Protocol):
    def ensure_project(self, project_id: str, name: str = "") -> None: ...

    def load_graph(self, project_id: str) -> ModelGraph: ...

    def list_entities(
        self, project_id: str, kind: EntityKind | None = None
    ) -> tuple[Entity, ...]: ...

    def append_patch(
        self, project_id: str, patch: Patch, expected_revision: int
    ) -> Revision: ...

    def list_issues(self, project_id: str) -> tuple[dict[str, object], ...]: ...


class RunRepository(Protocol):
    def create_run(self, run: Run) -> None: ...

    def update_step(self, step: Step) -> None: ...

    def load_run(self, project_id: str, run_id: str) -> Run | None: ...
