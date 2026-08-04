from __future__ import annotations

from pathlib import Path

from rflp_lite.adapters.readers import read_markdown
from rflp_lite.domain.models import Artifact, TextSpan


def ingest_requirements(path: Path) -> tuple[Artifact, tuple[TextSpan, ...]]:
    return read_markdown(path)

