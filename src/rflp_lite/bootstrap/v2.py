"""Composition root for the AI4MBSE Harness v2 services."""

from __future__ import annotations

from pathlib import Path

from rflp_lite.adapters.document_intelligence import LocalDocumentParser
from rflp_lite.application.analysis_service import AnalysisService
from rflp_lite.application.evidence_service import EvidenceService
from rflp_lite.application.model_service import ModelService
from rflp_lite.application.project_service import ProjectService
from rflp_lite.application.render_service import RenderService
from rflp_lite.application.settings_service import SettingsService
from rflp_lite.methodology.workflow import NoopRuntime, WorkflowRunner
from rflp_lite.repository.sqlite import SQLiteModelRepository


class V2Services:
    def __init__(self, workspace_root: Path, *, runtime=None, config_dir: Path | None = None):
        self.workspace_root = workspace_root.resolve()
        self.runtime = runtime or NoopRuntime()
        self.settings = SettingsService(config_dir)
        self.projects = ProjectService(
            self.workspace_root,
            lambda path: SQLiteModelRepository(path),
            LocalDocumentParser(),
        )
        self._repositories: dict[str, SQLiteModelRepository] = {}

    def repository(self, project_id: str) -> SQLiteModelRepository:
        repository = self._repositories.get(project_id)
        if repository is None:
            path = self.projects.path(project_id) / ".rflp" / "model.db"
            repository = SQLiteModelRepository(path)
            repository.ensure_project(project_id, project_id)
            self._repositories[project_id] = repository
        return repository

    def model(self, project_id: str) -> ModelService:
        return ModelService(self.repository(project_id))

    def analysis(self, project_id: str) -> AnalysisService:
        repository = self.repository(project_id)
        return AnalysisService(WorkflowRunner(repository, repository, self.runtime))

    def evidence(self, project_id: str) -> EvidenceService:
        return EvidenceService(self.repository(project_id))

    def render(self, project_id: str) -> RenderService:
        return RenderService(self.model(project_id))


def build_v2_services(workspace_root: Path, *, config_dir: Path | None = None) -> V2Services:
    return V2Services(workspace_root, config_dir=config_dir)
