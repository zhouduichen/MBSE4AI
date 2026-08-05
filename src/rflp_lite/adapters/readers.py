from __future__ import annotations

import ast
import hashlib
import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

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
    ".py",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
}
_WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


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


def _read_docx(content: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
    except (KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise AdapterFailure("invalid DOCX document") from exc
    paragraphs = []
    for paragraph in root.iter(f"{_WORD_NAMESPACE}p"):
        text = "".join(
            node.text or "" for node in paragraph.iter(f"{_WORD_NAMESPACE}t")
        ).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


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
    if len(content) > 5 * 1024 * 1024:
        raise AdapterFailure("artifact exceeds 5 MiB")
    safe_name = Path(filename).name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in _SUPPORTED_SUFFIXES:
        raise AdapterFailure("unsupported artifact type")
    try:
        text = _read_docx(content) if suffix == ".docx" else content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AdapterFailure("artifact must be UTF-8 text") from exc
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
