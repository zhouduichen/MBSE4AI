"""Narrow dependency bundles for application use cases.

The legacy :class:`ApplicationDependencies` remains available while the
application is migrated, but new use cases must depend on one of the focused
bundles in this module.  Keeping these bundles here makes the composition
root explicit without leaking concrete adapter types into the application
layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from rflp_lite.ports.generative_model import GenerativeModel
from rflp_lite.ports.jobs import JobRepositoryPort
from rflp_lite.ports.project_analysis import ProjectScannerPort, TestExecutionPort
from rflp_lite.ports.repositories import WorkbenchRepositoryPort


class ReviewPolicyPort(Protocol):
    def __call__(
        self,
        state: dict[str, object],
        group: str,
        item_id: str,
        decision: str,
        value: str,
        category: str,
    ) -> dict[str, object]: ...


class StalenessPolicyPort(Protocol):
    def __call__(
        self, state: dict[str, object], changed_ids: tuple[str, ...]
    ) -> tuple[str, ...]: ...


class RflpGeneratorPort(Protocol):
    def __call__(self, state: dict[str, object]) -> dict[str, object]: ...


class MbseGeneratorPort(Protocol):
    def __call__(
        self, state: dict[str, object], revision: int | None = None
    ) -> dict[str, object]: ...


class EvidenceRecorderPort(Protocol):
    def __call__(
        self, state: dict[str, object], evidence: tuple[dict[str, object], ...]
    ) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class ReanalyzeRequirementsDeps:
    """Ports needed to enqueue an incremental or full reanalysis."""

    load_state: Callable[[Any], dict[str, object] | None]
    runner_factory: Callable[[Path], Any]


@dataclass(frozen=True, slots=True)
class ReviewRequirementDeps:
    repository: WorkbenchRepositoryPort
    review_policy: ReviewPolicyPort
    staleness_policy: StalenessPolicyPort


@dataclass(frozen=True, slots=True)
class GenerateRflpDeps:
    repository: WorkbenchRepositoryPort
    generator: RflpGeneratorPort


@dataclass(frozen=True, slots=True)
class GenerateMbseDeps:
    repository: WorkbenchRepositoryPort
    generator: MbseGeneratorPort


@dataclass(frozen=True, slots=True)
class AnalyzeProjectDeps:
    repository: WorkbenchRepositoryPort
    project_analysis: ProjectScannerPort


@dataclass(frozen=True, slots=True)
class RunProjectTestsDeps:
    repository: WorkbenchRepositoryPort
    test_execution: TestExecutionPort


@dataclass(frozen=True, slots=True)
class RecordEvidenceDeps:
    repository: WorkbenchRepositoryPort
    recorder: EvidenceRecorderPort


@dataclass(frozen=True, slots=True)
class RunEnrichmentBlockDeps:
    model: GenerativeModel | None
    repository: WorkbenchRepositoryPort
    jobs: JobRepositoryPort
    semantic_validator: Any


@dataclass(frozen=True, slots=True)
class WorkspaceDeps:
    workspace_path: Path
    repository_factory: Callable[[Path], WorkbenchRepositoryPort]
