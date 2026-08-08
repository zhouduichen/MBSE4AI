"""Local document parser with optional PDF rendering and OCR adapters."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any

from rflp_lite.adapters.readers import _read_docx
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import AdapterFailure
from rflp_lite.domain.models import Artifact
from rflp_lite.domain.requirements import Diagnostic, DocumentRegion
from rflp_lite.ports.document_intelligence import (
    DocumentPage,
    DocumentParserPort,
    OcrPort,
    ParsedDocument,
)


MAX_DOCUMENT_BYTES = 50 * 1024 * 1024
MAX_DOCUMENT_PAGES = 500
SUPPORTED_DOCUMENT_SUFFIXES = {".txt", ".md", ".markdown", ".docx", ".pdf"}


def _region_id(artifact_id: str, page: int | None, locator: str, text: str) -> str:
    return f"region-{canonical_hash((artifact_id, page, locator, text))[:12]}"


class RapidOcrAdapter:
    """Lazy local RapidOCR adapter; model downloads are never implicit here."""

    def __init__(self, engine: Any = None):
        self._engine = engine

    def _load(self) -> Any:
        if self._engine is not None:
            return self._engine
        try:
            from rapidocr import RapidOCR
        except ImportError as exc:
            raise AdapterFailure(
                "OCR is unavailable; install the 'documents' optional dependencies"
            ) from exc
        self._engine = RapidOCR()
        return self._engine

    def extract(
        self, image: Any
    ) -> tuple[tuple[str, tuple[float, float, float, float]], ...]:
        result = self._load()(image)
        if isinstance(result, tuple):
            result = result[0]
        if not result:
            return ()
        values: list[tuple[str, tuple[float, float, float, float]]] = []
        if hasattr(result, "txts") and hasattr(result, "boxes"):
            iterable = zip(result.boxes, result.txts)
        else:
            iterable = result
        for item in iterable:
            if isinstance(item, dict):
                text = str(item.get("text", "")).strip()
                box = item.get("box") or item.get("bbox") or ()
            else:
                try:
                    box, text = item[0], item[1]
                except (IndexError, TypeError):
                    continue
                text = str(text).strip()
            if not text:
                continue
            flat = [float(point) for pair in box for point in (pair if isinstance(pair, (list, tuple)) else (pair,))]
            if len(flat) >= 8:
                bbox = (min(flat[0::2]), min(flat[1::2]), max(flat[0::2]), max(flat[1::2]))
            elif len(flat) >= 4:
                bbox = tuple(flat[:4])  # type: ignore[assignment]
            else:
                bbox = (0.0, 0.0, 0.0, 0.0)
            values.append((text, bbox))
        return tuple(values)

    def recognize(
        self, image: Any, *, page: int
    ) -> tuple[tuple[str, tuple[float, float, float, float], float], ...]:
        return tuple((text, bbox, 0.8) for text, bbox in self.extract(image))


class LocalDocumentParser(DocumentParserPort):
    """Parse supported engineering documents into page-aware regions."""

    def __init__(self, ocr: OcrPort | None = None):
        self.ocr = ocr or RapidOcrAdapter()

    def parse(self, filename: str, content: bytes) -> ParsedDocument:
        if not content:
            raise AdapterFailure("artifact is empty")
        if len(content) > MAX_DOCUMENT_BYTES:
            raise AdapterFailure("document exceeds 50 MiB")
        safe_name = Path(filename).name
        suffix = Path(safe_name).suffix.lower()
        if suffix not in SUPPORTED_DOCUMENT_SUFFIXES:
            raise AdapterFailure("unsupported artifact type")
        digest = hashlib.sha256(content).hexdigest()
        artifact = Artifact(
            id=f"artifact-{digest[:12]}",
            kind=suffix.lstrip("."),
            path=safe_name,
            sha256=digest,
        )
        if suffix == ".pdf":
            return self._parse_pdf(artifact, content)
        try:
            text = _read_docx(content) if suffix == ".docx" else content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AdapterFailure("document must be UTF-8 text") from exc
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            raise AdapterFailure("document contains no readable text")
        regions = tuple(
            DocumentRegion(
                id=_region_id(artifact.id, 1, f"paragraph-{index}", line),
                artifact_id=artifact.id,
                page=1,
                kind="paragraph",
                locator=f"paragraph-{index}",
                text=line,
            )
            for index, line in enumerate(lines, 1)
        )
        return ParsedDocument(
            artifact=artifact,
            pages=(DocumentPage(1),),
            regions=regions,
            text="\n".join(region.text for region in regions),
        )

    def _parse_pdf(self, artifact: Artifact, content: bytes) -> ParsedDocument:
        try:
            import pdfplumber
        except ImportError as exc:
            raise AdapterFailure(
                "PDF parsing is unavailable; install the 'documents' optional dependencies"
            ) from exc
        try:
            document = pdfplumber.open(io.BytesIO(content))
        except Exception as exc:  # library-specific PDF parse errors vary by version
            raise AdapterFailure("invalid PDF document") from exc
        pages: list[DocumentPage] = []
        regions: list[DocumentRegion] = []
        try:
            if len(document.pages) > MAX_DOCUMENT_PAGES:
                raise AdapterFailure("document exceeds 500 pages")
            for number, page in enumerate(document.pages, 1):
                pages.append(DocumentPage(number, float(page.width), float(page.height)))
                words = page.extract_words() or []
                lines: dict[tuple[float, float], list[dict[str, Any]]] = {}
                for word in words:
                    key = (round(float(word.get("top", 0.0)), 1), round(float(word.get("bottom", 0.0)), 1))
                    lines.setdefault(key, []).append(word)
                for line_number, word_group in enumerate(sorted(lines.values(), key=lambda group: min(float(item.get("top", 0.0)) for item in group)), 1):
                    ordered = sorted(word_group, key=lambda item: float(item.get("x0", 0.0)))
                    text = " ".join(str(item.get("text", "")).strip() for item in ordered).strip()
                    if not text:
                        continue
                    bbox = (
                        min(float(item.get("x0", 0.0)) for item in ordered),
                        min(float(item.get("top", 0.0)) for item in ordered),
                        max(float(item.get("x1", 0.0)) for item in ordered),
                        max(float(item.get("bottom", 0.0)) for item in ordered),
                    )
                    regions.append(DocumentRegion(_region_id(artifact.id, number, f"line-{line_number}", text), artifact.id, number, "text", f"page-{number}/line-{line_number}", text, bbox))
                if words:
                    continue
                try:
                    import pypdfium2
                except ImportError as exc:
                    raise AdapterFailure(
                        "scanned PDF requires pypdfium2 and RapidOCR; install the 'documents' extra"
                    ) from exc
                image = pypdfium2.PdfDocument(content)[number - 1].render(scale=2).to_pil()
                if hasattr(self.ocr, "recognize"):
                    recognized = self.ocr.recognize(image, page=number)  # type: ignore[attr-defined]
                else:
                    recognized = tuple((text, bbox, 0.8) for text, bbox in self.ocr.extract(image))
                for line_number, item in enumerate(recognized, 1):
                    text, bbox = item[0], item[1]
                    confidence = float(item[2]) if len(item) > 2 else 0.8
                    regions.append(DocumentRegion(_region_id(artifact.id, number, f"ocr-{line_number}", text), artifact.id, number, "ocr", f"page-{number}/ocr-{line_number}", text, bbox, confidence))
        finally:
            document.close()
        if not regions:
            raise AdapterFailure("PDF contains no readable text")
        return ParsedDocument(
            artifact=artifact,
            pages=tuple(pages),
            regions=tuple(regions),
            text="\n".join(region.text for region in regions),
        )


def parse_engineering_document(
    filename: str, content: bytes, *, ocr: OcrPort | None = None
) -> ParsedDocument:
    """Functional adapter entry point used by integrations and acceptance tests."""

    return LocalDocumentParser(ocr=ocr).parse(filename, content)
