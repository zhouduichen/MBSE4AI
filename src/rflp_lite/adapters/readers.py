from __future__ import annotations

import hashlib
import re
from pathlib import Path

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.models import Artifact, Claim, TextSpan


_OBLIGATION = re.compile(
    r"^(?P<subject>.+?)\s+(?P<predicate>MUST|SHALL)\s+(?P<object>.+?)[。.]?$",
    re.IGNORECASE,
)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_markdown(path: Path) -> tuple[Artifact, tuple[TextSpan, ...]]:
    digest = _file_hash(path)
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


class RuleClaimExtractor:
    def extract(self, spans: tuple[TextSpan, ...]) -> tuple[Claim, ...]:
        claims: list[Claim] = []
        for span in spans:
            match = _OBLIGATION.match(span.text)
            if match is None:
                continue
            subject = match.group("subject").strip()
            predicate = match.group("predicate").lower()
            object_value = match.group("object").strip()
            claim_id = f"claim-{canonical_hash((span.id, subject, predicate, object_value))[:12]}"
            claims.append(
                Claim(
                    id=claim_id,
                    span_id=span.id,
                    subject=subject,
                    predicate=predicate,
                    object=object_value,
                )
            )
        return tuple(claims)

