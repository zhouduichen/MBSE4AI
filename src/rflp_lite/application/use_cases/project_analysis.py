"""Orchestration for deterministic project analysis and persistence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rflp_lite.application.project_bridge import BridgeArtifacts
from rflp_lite.application.workspaces import WorkspaceRef
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.ports.repositories import RepositoryFactory


@dataclass(frozen=True, slots=True)
class ProjectAnalysisDependencies:
    """Only the capabilities needed by the project-analysis use case."""

    repository_factory: RepositoryFactory
    load_state: Callable[[WorkspaceRef], dict[str, object] | None]
    analyze_state: Callable[
        [dict[str, object], str | Path], tuple[dict[str, object], BridgeArtifacts]
    ]


class ProjectAnalysisService:
    """Analyze a project against the approved baseline and persist its results."""

    def __init__(self, dependencies: ProjectAnalysisDependencies):
        self.dependencies = dependencies

    def analyze(self, workspace: WorkspaceRef, source: str | Path) -> dict[str, object]:
        current = self.dependencies.load_state(workspace)
        if current is None:
            raise ContractViolation("requirements workbench is empty")
        expected_revision = int(current.get("revision", 0) or 0)
        expected_content_revision = int(
            current.get("content_revision", current.get("revision", 0)) or 0
        )

        state, artifacts = self.dependencies.analyze_state(current, source)
        repository = self.dependencies.repository_factory(
            workspace.path / ".rflp" / "model.db"
        )
        try:
            with repository.transaction():
                repository.save_workbench(
                    state,
                    expected_revision=expected_revision,
                    expected_content_revision=expected_content_revision,
                )
                repository.save_baseline(artifacts.baseline)
                repository.save_evidence(artifacts.evidence)
                repository.save_tasks(artifacts.tasks)
                project = state.get("project") or {}
                repository.record_audit(
                    "project.analyzed",
                    {
                        "source": str(project.get("source", "")),
                        "missing": sum(
                            1
                            for item in artifacts.delta.items
                            if item.kind == "MISSING"
                        ),
                        "extra": sum(
                            1 for item in artifacts.delta.items if item.kind == "EXTRA"
                        ),
                        "tasks": len(artifacts.tasks),
                    },
                )
        finally:
            repository.close()
        return state
