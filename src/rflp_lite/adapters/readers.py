from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path

from rflp_lite.adapters.documents.docx_reader import read_docx_text
from rflp_lite.adapters.documents.markdown_reader import read_markdown
from rflp_lite.adapters.documents.txt_reader import read_utf8_text
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import AdapterFailure
from rflp_lite.domain.models import Artifact, Claim, TextSpan


_OBLIGATION = re.compile(
    r"^(?P<subject>.+?)\s*(?P<predicate>MUST NOT|MUST|SHALL|SHOULD|必须|应当|不得|禁止|需要|可以)\s*(?P<object>.+?)[。.]?$",
    re.IGNORECASE,
)
_SUPPORTED_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".docx",
    ".pdf",
    ".py",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
}
def _python_symbols(text: str) -> tuple[str, ...]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise AdapterFailure(f"invalid Python source: line {exc.lineno}") from exc
    return tuple(
        f"{type(node).__name__} {node.name}"
        for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    )


def read_artifact(
    filename: str, content: bytes
) -> tuple[Artifact, tuple[TextSpan, ...]]:
    if not content:
        raise AdapterFailure("artifact is empty")
    safe_name = Path(filename).name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in _SUPPORTED_SUFFIXES:
        raise AdapterFailure("unsupported artifact type")
    limit = 50 * 1024 * 1024 if suffix == ".pdf" else 5 * 1024 * 1024
    if len(content) > limit:
        raise AdapterFailure(f"artifact exceeds {'50 MiB' if suffix == '.pdf' else '5 MiB'}")
    if suffix == ".pdf":
        from rflp_lite.adapters.document_intelligence import parse_engineering_document

        parsed = parse_engineering_document(safe_name, content)
        return parsed.artifact, tuple(
            TextSpan(
                id=region.id.replace("region-", "span-", 1),
                artifact_id=region.artifact_id,
                locator=region.locator,
                text=region.text,
            )
            for region in parsed.regions
        )
    text = (
        read_docx_text(content)
        if suffix == ".docx"
        else read_utf8_text(content)
    )
    lines = [line.strip(" -*\t") for line in text.splitlines() if line.strip(" -*\t")]
    if suffix == ".py":
        lines.extend(_python_symbols(text))
    digest = hashlib.sha256(content).hexdigest()
    artifact = Artifact(
        id=f"artifact-{digest[:12]}",
        kind=suffix.lstrip("."),
        path=safe_name,
        sha256=digest,
    )
    spans = tuple(
        TextSpan(
            id=f"span-{canonical_hash((artifact.id, index, line))[:12]}",
            artifact_id=artifact.id,
            locator=f"paragraph-{index}",
            text=line,
        )
        for index, line in enumerate(lines, 1)
    )
    if not spans:
        raise AdapterFailure("artifact contains no readable text")
    return artifact, spans


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
