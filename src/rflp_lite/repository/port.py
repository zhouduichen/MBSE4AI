"""Persistence ports for the typed Model Graph and Run Ledger."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence

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
    output_hash: str = ""
    provider_id: str = ""
    model_id: str = ""
    prompt_template_id: str = ""
    context_hash: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    prompt_version: str = ""
    prompt_hash: str = ""


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
    provider_id: str = ""
    model_id: str = ""
    execution_mode: str = ""
    context_hash: str = ""
    task_spec_hash: str = ""
    prompt_hash: str = ""
    output_hash: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    lease: str = ""
    heartbeat: float = 0.0


class ModelRepository(Protocol):
    def ensure_project(self, project_id: str, name: str = "") -> None: ...

    def load_graph(self, project_id: str) -> ModelGraph: ...

    def list_entities(
        self, project_id: str, kind: EntityKind | None = None
    ) -> tuple[Entity, ...]: ...

    def append_patch(
        self, project_id: str, patch: Patch, expected_revision: int, *, run_id: str | None = None
    ) -> Revision: ...

    def list_issues(self, project_id: str) -> tuple[dict[str, object], ...]: ...

    def save_issue(self, project_id: str, issue: Mapping[str, object]) -> None: ...

    def save_document(self, project_id: str, document: Mapping[str, object]) -> None: ...

    def save_source_regions(
        self, project_id: str, regions: Sequence[Mapping[str, object]]
    ) -> None: ...

    def has_documents(self, project_id: str) -> bool: ...

    def save_evidence(self, project_id: str, evidence: Mapping[str, object]) -> None: ...

    def list_evidence(self, project_id: str) -> tuple[dict[str, object], ...]: ...

    def search_fts(
        self, project_id: str, query: str, limit: int = 20
    ) -> tuple[dict[str, object], ...]: ...

    def audit_summary(self, project_id: str, run_id: str) -> dict[str, object]: ...

    def save_closure(self, project_id: str, run_id: str, payload: Mapping[str, object]) -> None: ...

    def freeze_revision(self, project_id: str, revision: int) -> None: ...

    def record_audit(self, project_id: str, kind: str, payload: Mapping[str, object]) -> None: ...


class RunRepository(Protocol):
    def create_run(self, run: Run) -> None: ...

    def update_step(self, step: Step) -> None: ...

    def update_run(self, run_id: str, status: str, diagnostics: tuple[str, ...] = ()) -> None: ...

    def load_run(self, project_id: str, run_id: str) -> Run | None: ...

    def claim_run(self, project_id: str, run_id: str, lease: str, now: float) -> bool: ...

    def heartbeat_run(self, run_id: str, lease: str, now: float) -> None: ...

    def interrupt_run(self, run_id: str, lease: str) -> None: ...
