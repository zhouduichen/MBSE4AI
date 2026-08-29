"""Runtime dependency bundle for application services.

This module contains only protocols, factories, and a small compatibility
registry. Concrete implementations are assembled by ``bootstrap.container``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from rflp_lite.ports.generative_model import GenerativeModel
from rflp_lite.ports.jobs import BackgroundExecutorPort, JobRepositoryPort
from rflp_lite.ports.repositories import RepositoryFactory


@dataclass(frozen=True, slots=True)
class ApplicationDependencies:
    repository_factory: RepositoryFactory
    job_service_factory: Callable[[Path], Any]
    job_repository_factory: Callable[[Path], JobRepositoryPort]
    job_executor_factory: Callable[[], BackgroundExecutorPort]
    document_parser_factory: Callable[[], Any]
    artifact_reader: Callable[[str, bytes], Any]
    markdown_reader: Callable[[Path], Any]
    claim_extractor_factory: Callable[[], Any]
    model_factory: Callable[[dict[str, object]], GenerativeModel | None]
    evidence_readers: Callable[[Path], tuple[Any, ...]]
    solver_factory: Callable[[str], Any]
    project_scanner: Callable[[Path], tuple[Any, dict[str, object]]]
    test_executor: Callable[..., tuple[Any, ...]]
    diagram_engine_factory: Callable[[str], Any]
    svg_renderer_factory: Callable[[], Any]
    discipline_registry: Callable[[], dict[str, object]]
    scheme_reader: Callable[[str, bytes | str], tuple[dict[str, object], ...]]
    sqlite_scheme_reader: Callable[[Path, str], tuple[dict[str, object], ...]]
    tracking: Callable[..., dict[str, object]]
    test_connection: Callable[[dict[str, object]], dict[str, object]]


_DEFAULT_DEPENDENCIES: ApplicationDependencies | None = None


def configure_default_dependencies(value: ApplicationDependencies) -> None:
    global _DEFAULT_DEPENDENCIES
    _DEFAULT_DEPENDENCIES = value


def configured_dependencies(
    value: ApplicationDependencies | None = None,
) -> ApplicationDependencies:
    """Resolve the legacy default only at compatibility boundaries.

    New use cases receive focused dependency bundles directly.  This helper
    remains for the pre-container public functions and is intentionally kept
    out of the use-case package.
    """
    dependencies = value or _DEFAULT_DEPENDENCIES
    if dependencies is None:
        raise RuntimeError(
            "application dependencies are not configured; use bootstrap.container.build_container()"
        )
    return dependencies


# Compatibility alias for legacy public functions while callers migrate to
# explicit dependency bundles.
require_dependencies = configured_dependencies
