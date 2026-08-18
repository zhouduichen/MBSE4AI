from __future__ import annotations

from pathlib import Path

from rflp_lite.application.dependencies import ApplicationDependencies, require_dependencies
from rflp_lite.domain.models import Artifact, TextSpan


def ingest_requirements(
    path: Path,
    *,
    dependencies: ApplicationDependencies | None = None,
) -> tuple[Artifact, tuple[TextSpan, ...]]:
    deps = require_dependencies(dependencies)
    return deps.markdown_reader(path)
