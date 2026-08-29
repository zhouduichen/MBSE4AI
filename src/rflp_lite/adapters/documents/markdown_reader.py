"""Markdown artifact reader."""

from __future__ import annotations

import hashlib
from pathlib import Path

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.models import Artifact, TextSpan


def read_markdown(path: Path) -> tuple[Artifact, tuple[TextSpan, ...]]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    artifact = Artifact(
        id=f"artifact-{digest[:12]}",
        kind="markdown",
        path=path.name,
        sha256=digest,
    )
    spans: list[TextSpan] = []
    heading = "document"
    item_index = 0
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            continue
        if not line.startswith(("- ", "* ")):
            continue
        item_index += 1
        text = line[2:].strip()
        locator = f"{heading}/item-{item_index}/line-{line_number}"
        span_id = f"span-{canonical_hash((artifact.id, locator, text))[:12]}"
        spans.append(TextSpan(span_id, artifact.id, locator, text))
    return artifact, tuple(spans)
