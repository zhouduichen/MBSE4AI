"""Technology-neutral ports for engineering document intelligence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from rflp_lite.domain.documents import Artifact
from rflp_lite.domain.requirements import Diagnostic, DocumentRegion


@dataclass(frozen=True, slots=True)
class DocumentPage:
    number: int
    width: float | None = None
    height: float | None = None
    image: Any = None


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    artifact: Artifact
    pages: tuple[DocumentPage, ...]
    regions: tuple[DocumentRegion, ...]
    text: str
    diagnostics: tuple[Diagnostic, ...] = ()


class OcrPort(Protocol):
    def extract(self, image: Any) -> tuple[tuple[str, tuple[float, float, float, float]], ...]: ...

    def recognize(self, image: Any, *, page: int) -> tuple[tuple[str, tuple[float, float, float, float], float], ...]: ...


class DocumentParserPort(Protocol):
    def parse(self, filename: str, content: bytes) -> ParsedDocument: ...
