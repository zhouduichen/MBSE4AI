"""Composition root for the AI4MBSE Harness v2 services."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from rflp_lite.adapters.document_intelligence import LocalDocumentParser
from rflp_lite.adapters.llm_client import test_connection as test_llm_connection
from rflp_lite.application.analysis_service import AnalysisService
from rflp_lite.application.deliverables import EngineeringDeliverableService
from rflp_lite.application.evidence_service import EvidenceService
from rflp_lite.application.model_service import ModelService
from rflp_lite.application.model_generation import ModelGenerationService
from rflp_lite.application.project_service import ProjectService
from rflp_lite.application.requirement_input import RequirementInputService
from rflp_lite.application.render_service import RenderService
from rflp_lite.application.review_service import ReviewService
from rflp_lite.application.settings_service import SettingsService
from rflp_lite.methodology.workflow import WorkflowRunner
from rflp_lite.repository.sqlite import SQLiteModelRepository
from rflp_lite.runtime.factory import RuntimeFactory


class V2Services:
    def __init__(
        self,
        workspace_root: Path,
        *,
        runtime=None,
        runtime_config: Mapping[str, object] | None = None,
        config_dir: Path | None = None,
    ):
        self.workspace_root = workspace_root.resolve()
        self._runtime_override = runtime
        self._runtime_config = dict(runtime_config) if runtime_config else None
        self.runtime_factory = RuntimeFactory()
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

    def delete_project(self, project_id: str) -> dict[str, str]:
        repository = self._repositories.pop(project_id, None)
        if repository is not None:
            repository.close()
        return self.projects.delete(project_id)

    def model(self, project_id: str) -> ModelService:
        return ModelService(self.repository(project_id))

    def analysis(self, project_id: str) -> AnalysisService:
        repository = self.repository(project_id)
        selection = self.runtime_factory.select(
            self.settings.active_config() or self._runtime_config,
            runtime_override=self._runtime_override,
        )
        return AnalysisService(
            WorkflowRunner(
                repository,
                repository,
                selection.runtime,
                runtime_selection=selection,
            )
        )

    def generation(self, project_id: str) -> ModelGenerationService:
        repository = self.repository(project_id)
        selection = self.runtime_factory.select(
            self.settings.active_config() or self._runtime_config,
            runtime_override=self._runtime_override,
        )
        return ModelGenerationService(
            repository,
            selection.runtime,
            runtime_selection=selection,
        )

    def requirements_input(self, project_id: str) -> RequirementInputService:
        return RequirementInputService(self.repository(project_id), project_id)

    def evidence(self, project_id: str) -> EvidenceService:
        return EvidenceService(self.repository(project_id))

    def test_model_profile(self, config: Mapping[str, object]) -> Mapping[str, object]:
        return test_llm_connection(config)

    def render(self, project_id: str) -> RenderService:
        return RenderService(self.model(project_id))

    def deliverables(self, project_id: str) -> EngineeringDeliverableService:
        return EngineeringDeliverableService(self.model(project_id))

    def review(self, project_id: str) -> ReviewService:
        return ReviewService(self.model(project_id))


def build_v2_services(
    workspace_root: Path,
    *,
    runtime=None,
    runtime_config: Mapping[str, object] | None = None,
    config_dir: Path | None = None,
) -> V2Services:
    # Library/test callers are isolated by default.  The real CLI and web
    # composition roots pass the user profile directory explicitly.
    effective_config_dir = config_dir if config_dir is not None else workspace_root.resolve() / ".rflp-config"
    return V2Services(
        workspace_root,
        runtime=runtime,
        runtime_config=runtime_config,
        config_dir=effective_config_dir,
    )
