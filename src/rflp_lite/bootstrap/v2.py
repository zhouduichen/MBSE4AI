"""Composition root for the AI4MBSE Harness v2 services."""

from __future__ import annotations

import os
from pathlib import Path
from collections.abc import Sequence
from typing import Mapping
from urllib.parse import urlparse

from rflp_lite.adapters.document_intelligence import LocalDocumentParser
from rflp_lite.adapters.cad_preview import PreviewCadAdapter
from rflp_lite.adapters.freecad_remote import FreeCadRemoteAdapter, FreeCadRemoteConfig
from rflp_lite.adapters.freecad_review import FreeCadDesignRuleAdapter, FreeCadDrawingAdapter
from rflp_lite.adapters.design_rules_preview import PreviewDesignRuleAdapter
from rflp_lite.adapters.drawing_preview import PreviewDrawingAdapter
from rflp_lite.adapters.disciplines import discipline_registry
from rflp_lite.adapters.llm_client import test_connection as test_llm_connection
from rflp_lite.adapters.scheme_sources import read_scheme_rows
from rflp_lite.application.analysis_service import AnalysisService
from rflp_lite.application.deliverables import EngineeringDeliverableService
from rflp_lite.application.evidence_service import EvidenceService
from rflp_lite.application.engineering_tools import (
    EngineeringTool,
    EngineeringToolService,
)
from rflp_lite.application.model_service import ModelService
from rflp_lite.application.model_generation import ModelGenerationService
from rflp_lite.application.product_flow import EngineeringProductFlowService
from rflp_lite.application.project_service import ProjectService
from rflp_lite.application.project_context import ProjectContextService
from rflp_lite.application.requirement_input import RequirementInputService
from rflp_lite.application.requirements_use_case import RequirementsUseCaseService
from rflp_lite.application.concept_project_service import ConceptDesignProjectService
from rflp_lite.application.cad_workflow import CadWorkflowService
from rflp_lite.application.design_intent import DesignIntentService
from rflp_lite.application.design_review_service import DesignReviewService
from rflp_lite.application.render_service import RenderService
from rflp_lite.application.review_service import ReviewService
from rflp_lite.application.settings_service import SettingsService
from rflp_lite.application.tool_layer import EngineeringToolLayer
from rflp_lite.application.vv_execution import VvExecutionService
from rflp_lite.methodology.workflow import WorkflowRunner
from rflp_lite.methodology.llm_controller import LLMController
from rflp_lite.repository.sqlite import SQLiteModelRepository
from rflp_lite.methodology.context import ContextBuilder
from rflp_lite.retrieval.evidence import RetrievalEngine
from rflp_lite.retrieval.history import HistoricalProjectRetriever
from rflp_lite.runtime.factory import RuntimeFactory


class V2Services:
    def __init__(
        self,
        workspace_root: Path,
        *,
        runtime=None,
        runtime_config: Mapping[str, object] | None = None,
        config_dir: Path | None = None,
        engineering_tools: Sequence[EngineeringTool] = (),
        verifier_enabled: bool = True,
    ):
        self.workspace_root = workspace_root.resolve()
        self._runtime_override = runtime
        self._runtime_config = dict(runtime_config) if runtime_config else None
        self._engineering_tools = tuple(engineering_tools)
        self.verifier_enabled = verifier_enabled
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

    def analysis(self, project_id: str, *, profile_id: str | None = None) -> AnalysisService:
        repository = self.repository(project_id)
        config = self._selection_config(profile_id)
        selection = self.runtime_factory.select(
            config,
            runtime_override=self._runtime_override,
        )
        return AnalysisService(
            WorkflowRunner(
                repository,
                repository,
                selection.runtime,
                context_builder=ContextBuilder(self._retrieval_engine(project_id, repository)),
                runtime_selection=selection,
                verifier_enabled=self.verifier_enabled,
            )
        )

    def generation(self, project_id: str, *, profile_id: str | None = None) -> ModelGenerationService:
        repository = self.repository(project_id)
        config = self._selection_config(profile_id)
        selection = self.runtime_factory.select(
            config,
            runtime_override=self._runtime_override,
        )
        retrieval_engine = self._retrieval_engine(project_id, repository)
        return ModelGenerationService(
            repository,
            selection.runtime,
            runtime_selection=selection,
            llm_controller=LLMController(selection.controller_model),
            context_builder=ContextBuilder(retrieval_engine),
            tool_layer=EngineeringToolLayer(repository, retrieval_engine=retrieval_engine),
        )

    def _selection_config(self, profile_id: str | None) -> Mapping[str, object] | None:
        if profile_id:
            return self.settings.profile_config(profile_id)
        if self._runtime_config is not None:
            return self._runtime_config
        return self.settings.active_config()

    def requirements_input(self, project_id: str) -> RequirementInputService:
        return RequirementInputService(self.repository(project_id), project_id)

    def requirements_use_case(
        self,
        project_id: str,
        *,
        profile_id: str | None = None,
    ) -> RequirementsUseCaseService:
        """Build the document-to-behavior intake service for one profile.

        The selected runtime owns the concrete remote model.  Rule runtimes
        intentionally expose no model and therefore produce an explicit
        degraded draft instead of starting a local model implicitly.
        """

        config = self._selection_config(profile_id)
        host = urlparse(str(config.get("base_url", ""))).hostname if config else None
        loopback = host in {None, "localhost", "127.0.0.1", "::1", "0.0.0.0"}
        tunneled_remote = bool(config) and str(config.get("model_location", "")).casefold() == "remote"
        use_remote_profile = profile_id is not None and (not loopback or tunneled_remote)
        selection = self.runtime_factory.select(
            config if use_remote_profile else None,
            runtime_override=self._runtime_override if use_remote_profile else None,
        )
        return RequirementsUseCaseService(
            self.repository(project_id),
            project_id,
            model=getattr(selection.runtime, "model", None),
            profile_id=selection.profile_id,
            provider_id=selection.provider_id,
            model_id=selection.model_id,
            max_output_tokens=selection.max_output_tokens or 4096,
        )

    def context(self, project_id: str) -> ProjectContextService:
        return ProjectContextService(self.repository(project_id), project_id)

    def concept_design(self, project_id: str) -> ConceptDesignProjectService:
        return ConceptDesignProjectService(
            self.repository(project_id),
            project_id,
            registry_factory=discipline_registry,
            scheme_reader=read_scheme_rows,
        )

    def cad_design(self, project_id: str, *, profile_id: str | None = None) -> CadWorkflowService:
        config = self._selection_config(profile_id)
        # CAD intent extraction must never silently start a model on this
        # machine.  A remote HTTP endpoint, including a model hosted on a
        # linked SSH/Tailscale server, is allowed only when its profile is
        # explicitly selected.  An omitted profile always uses the offline
        # clarification parser.
        host = urlparse(str(config.get("base_url", ""))).hostname if config else None
        loopback = host in {None, "localhost", "127.0.0.1", "::1", "0.0.0.0"}
        tunneled_remote = bool(config) and str(config.get("model_location", "")).casefold() == "remote"
        use_remote_profile = profile_id is not None and (not loopback or tunneled_remote)
        selection = self.runtime_factory.select(
            config if use_remote_profile else None,
            runtime_override=self._runtime_override if use_remote_profile else None,
        )
        return CadWorkflowService(
            self.repository(project_id),
            project_id,
            cad=self._cad_adapter(project_id),
            intent_service=DesignIntentService(
                model=getattr(selection.runtime, "model", None),
                provider_id=selection.provider_id,
                model_id=selection.model_id,
            ),
        )

    def design_review(self, project_id: str) -> DesignReviewService:
        real_cad = self._real_cad_enabled()
        return DesignReviewService(
            self.repository(project_id),
            project_id,
            drawing=FreeCadDrawingAdapter() if real_cad else PreviewDrawingAdapter(),
            rules=FreeCadDesignRuleAdapter() if real_cad else PreviewDesignRuleAdapter(),
        )

    def _cad_adapter(self, project_id: str):
        if not self._real_cad_enabled():
            return PreviewCadAdapter()
        artifact_root = self.projects.path(project_id) / ".rflp" / "cad_artifacts"
        return FreeCadRemoteAdapter(FreeCadRemoteConfig.from_env(artifact_root))

    @staticmethod
    def _real_cad_enabled() -> bool:
        return os.getenv("AI4MBSE_CAD_BACKEND", "preview").strip().casefold() == "freecad-remote"

    def evidence(self, project_id: str) -> EvidenceService:
        repository = self.repository(project_id)
        return EvidenceService(repository, retrieval_engine=self._retrieval_engine(project_id, repository))

    def vv(self, project_id: str) -> VvExecutionService:
        return VvExecutionService(self.model(project_id))

    def tools(self, project_id: str) -> EngineeringToolService:
        return EngineeringToolService(
            self.model(project_id),
            self.vv(project_id),
            tools=self._engineering_tools,
        )

    def _retrieval_engine(self, project_id: str, repository) -> RetrievalEngine:
        sources = tuple(
            (
                item.name,
                item.path / ".rflp" / "model.db",
            )
            for item in self.projects.list()
            if item.name != project_id
        )
        historical = HistoricalProjectRetriever(
            repository,
            project_sources=sources,
            repository_factory=SQLiteModelRepository,
        )
        return RetrievalEngine(repository, historical_retriever=historical)

    def test_model_profile(self, config: Mapping[str, object]) -> Mapping[str, object]:
        return test_llm_connection(config)

    def render(self, project_id: str) -> RenderService:
        return RenderService(self.model(project_id))

    def deliverables(self, project_id: str) -> EngineeringDeliverableService:
        return EngineeringDeliverableService(
            self.model(project_id),
            evidence_repository=self.repository(project_id),
        )

    def product_flow(
        self,
        project_id: str,
        *,
        profile_id: str | None = None,
    ) -> EngineeringProductFlowService:
        return EngineeringProductFlowService(
            self.generation(project_id, profile_id=profile_id),
            self.concept_design(project_id),
            self.cad_design(project_id, profile_id=profile_id),
            self.design_review(project_id),
            self.deliverables(project_id),
        )

    def review(self, project_id: str) -> ReviewService:
        return ReviewService(self.model(project_id))


def build_v2_services(
    workspace_root: Path,
    *,
    runtime=None,
    runtime_config: Mapping[str, object] | None = None,
    config_dir: Path | None = None,
    engineering_tools: Sequence[EngineeringTool] = (),
    verifier_enabled: bool = True,
) -> V2Services:
    # Library/test callers are isolated by default.  The real CLI and web
    # composition roots pass the user profile directory explicitly.
    effective_config_dir = config_dir if config_dir is not None else workspace_root.resolve() / ".rflp-config"
    return V2Services(
        workspace_root,
        runtime=runtime,
        runtime_config=runtime_config,
        config_dir=effective_config_dir,
        engineering_tools=engineering_tools,
        verifier_enabled=verifier_enabled,
    )
