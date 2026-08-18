"""Concrete adapter assembly for CLI and Web startup."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rflp_lite.adapters.deterministic_svg_renderer import DeterministicSvgRenderer
from rflp_lite.adapters.disciplines import discipline_registry
from rflp_lite.adapters.document_intelligence import LocalDocumentParser
from rflp_lite.adapters.evidence_readers import read_junit, read_openapi, read_python_ast
from rflp_lite.adapters.graphviz_engine import GraphvizEngine
from rflp_lite.adapters.llm_client import chat_completion, test_connection
from rflp_lite.adapters.matrix_engine import MatrixEngine
from rflp_lite.adapters.mlflow_tracking import track_run_with_mlflow
from rflp_lite.adapters.openai_compatible_model import OpenAICompatibleModel
from rflp_lite.adapters.plantuml_engine import PlantUMLEngine
from rflp_lite.adapters.project_scanner import scan_project
from rflp_lite.adapters.readers import RuleClaimExtractor, read_artifact, read_markdown
from rflp_lite.adapters.scheme_sources import read_scheme_rows, read_sqlite_scheme_rows
from rflp_lite.adapters.solvers import CpSatSolver, HeuristicSolver
from rflp_lite.adapters.sqlite_repository import SQLiteRepository
from rflp_lite.adapters.test_executor import run_project_test_matrix
from rflp_lite.application.dependencies import (
    ApplicationDependencies,
    configure_default_dependencies,
)
from rflp_lite.application.jobs import JobService


def _evidence_readers(root: Path) -> tuple[object, ...]:
    return (
        *read_openapi(root / "openapi.json"),
        *read_junit(root / "junit.xml"),
        *read_python_ast(root / "implementation.py"),
    )


def _model_factory(config: dict[str, object]) -> OpenAICompatibleModel | None:
    return OpenAICompatibleModel(config) if config else None


def _solver_factory(name: str) -> object:
    return CpSatSolver() if name == "cp-sat" else HeuristicSolver()


def _diagram_engine_factory(name: str) -> object:
    if name == "graphviz":
        return GraphvizEngine()
    if name == "plantuml":
        return PlantUMLEngine()
    if name == "matrix":
        return MatrixEngine()
    raise ValueError(f"unsupported diagram engine: {name}")


@dataclass(frozen=True, slots=True)
class ApplicationContainer:
    workspace_root: Path
    fixture_root: Path | None
    dependencies: ApplicationDependencies


def build_container(
    workspace_root: Path, fixture_root: Path | None = None
) -> ApplicationContainer:
    dependencies = ApplicationDependencies(
        repository_factory=lambda path: SQLiteRepository(path),
        job_service_factory=lambda path: JobService(path),
        document_parser_factory=lambda: LocalDocumentParser(),
        artifact_reader=read_artifact,
        markdown_reader=read_markdown,
        claim_extractor_factory=lambda: RuleClaimExtractor(),
        chat_completion=chat_completion,
        model_factory=_model_factory,
        evidence_readers=_evidence_readers,
        solver_factory=_solver_factory,
        project_scanner=scan_project,
        test_executor=run_project_test_matrix,
        diagram_engine_factory=_diagram_engine_factory,
        svg_renderer_factory=lambda: DeterministicSvgRenderer(),
        discipline_registry=discipline_registry,
        scheme_reader=read_scheme_rows,
        sqlite_scheme_reader=read_sqlite_scheme_rows,
        tracking=track_run_with_mlflow,
        test_connection=test_connection,
    )
    configure_default_dependencies(dependencies)
    return ApplicationContainer(
        workspace_root=workspace_root.resolve(),
        fixture_root=fixture_root,
        dependencies=dependencies,
    )
