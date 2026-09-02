"""Repository contracts used by the application layer.

The protocols deliberately describe the aggregate operations rather than the
SQLite schema.  Concrete persistence remains an adapter concern.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from rflp_lite.domain.models import (
    Artifact,
    Baseline,
    Candidate,
    Claim,
    Evidence,
    ModelElement,
    Relation,
    SimulationRun,
    TaskContract,
    TextSpan,
)


class WorkbenchRepositoryPort(Protocol):
    def close(self) -> None: ...

    def transaction(self) -> AbstractContextManager[None]: ...

    def load_workbench(self) -> dict[str, object] | None: ...

    def load_workbench_summary(self) -> Mapping[str, object] | None: ...

    def workbench_exists(self) -> bool: ...

    def save_workbench(
        self,
        value: dict[str, object],
        event: str = "workbench.saved",
        *,
        expected_revision: int | None = None,
        expected_content_revision: int | None = None,
    ) -> dict[str, object]: ...

    def record_audit(self, kind: str, payload: dict[str, object]) -> int: ...

    def audit_events(self, kind: str | None = None) -> tuple[dict[str, object], ...]: ...

    def save_artifacts(self, values: tuple[Artifact, ...]) -> None: ...

    def save_spans(self, values: tuple[TextSpan, ...]) -> None: ...

    def save_claims(self, values: tuple[Claim, ...]) -> None: ...

    def save_elements(self, values: tuple[ModelElement, ...]) -> None: ...

    def save_relations(self, values: tuple[Relation, ...]) -> None: ...

    def save_candidates(self, values: tuple[Candidate, ...]) -> None: ...

    def save_simulation(self, value: SimulationRun) -> None: ...

    def save_baseline(self, value: Baseline) -> Baseline: ...

    def save_tasks(self, values: tuple[TaskContract, ...]) -> None: ...

    def save_evidence(self, values: tuple[Evidence, ...]) -> None: ...

    def save_domain_pack(self, value: Mapping[str, object]) -> dict[str, object]: ...

    def save_scheme_records(self, values: tuple[object, ...]) -> None: ...

    def scheme_records(self) -> tuple[dict[str, object], ...]: ...

    def concept_runs(self) -> tuple[dict[str, object], ...]: ...

    def load_concept_run(self, run_id: str) -> dict[str, object] | None: ...

    def save_workflow_runs(self, values: tuple[Mapping[str, object], ...]) -> None: ...

    def workflow_runs(self) -> tuple[dict[str, object], ...]: ...

    def load_workflow_run(self, run_id: str) -> dict[str, object] | None: ...

    def candidate_reviews(self) -> tuple[dict[str, object], ...]: ...

    def save_requirement_records(
        self, values: tuple[dict[str, object], ...], sequence: int, event: str
    ) -> None: ...

    def requirement_records(self) -> tuple[dict[str, object], ...]: ...

    def mark_requirement_deleted(
        self, requirement_ids: tuple[str, ...], sequence: int, event: str
    ) -> None: ...

    def save_trace_records(self, values: tuple[dict[str, object], ...]) -> None: ...


RepositoryFactory = Callable[[Path], WorkbenchRepositoryPort]


class UnitOfWorkPort(Protocol):
    def __enter__(self) -> None: ...

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None: ...


def repository_method(repository: WorkbenchRepositoryPort, name: str, *args: Any, **kwargs: Any) -> Any:
    """Small typed escape hatch for compatibility-only aggregate methods."""

    return getattr(repository, name)(*args, **kwargs)
