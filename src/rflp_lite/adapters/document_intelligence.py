"""Local document parser with optional PDF rendering and OCR adapters."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from rflp_lite.adapters.documents.docx_reader import read_docx_blocks
from rflp_lite.adapters.documents.ocr import RapidOcrAdapter
from rflp_lite.adapters.documents.pdf_reader import open_pdf
from rflp_lite.adapters.documents.txt_reader import read_utf8_text
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


def _needs_hybrid_ocr(words: list[dict[str, Any]], width: float, height: float) -> bool:
    """Return whether a page has too little extracted text to trust PDF text."""

    characters = sum(len(str(item.get("text", ""))) for item in words)
    page_area = max(width * height, 1.0)
    return characters < 24 or characters / page_area < 0.00008


def _normalise_text(value: str) -> str:
    return " ".join(str(value).split()).casefold()


def _overlapping_boxes(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    if len(first) != 4 or len(second) != 4:
        return False
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    return right > left and bottom > top


def _is_duplicate_region(
    text: str,
    bbox: tuple[float, float, float, float],
    regions: list[DocumentRegion],
) -> bool:
    normalized = _normalise_text(text)
    if not normalized:
        return True
    return any(
        _normalise_text(region.text) == normalized
        and _overlapping_boxes(region.bbox, bbox)
        for region in regions
    )


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
        if suffix == ".docx":
            blocks = read_docx_blocks(content)
            if not blocks:
                raise AdapterFailure("document contains no readable text")
            regions = tuple(
                DocumentRegion(
                    id=_region_id(artifact.id, 1, block.locator, block.text),
                    artifact_id=artifact.id,
                    page=1,
                    kind=block.kind,
                    locator=block.locator,
                    text=block.text,
                    heading_path=block.heading_path,
                    table_id=block.table_id,
                    row_index=block.row_index,
                    column_index=block.column_index,
                )
                for block in blocks
            )
        else:
            text = read_utf8_text(content, label="document")
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
        document = open_pdf(content)
        pages: list[DocumentPage] = []
        regions: list[DocumentRegion] = []
        diagnostics: list[Diagnostic] = []
        try:
            if len(document.pages) > MAX_DOCUMENT_PAGES:
                raise AdapterFailure("document exceeds 500 pages")
            for number, page in enumerate(document.pages, 1):
                pages.append(DocumentPage(number, float(page.width), float(page.height)))
                words = page.extract_words() or []
                width = float(page.width)
                height = float(page.height)
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
                    regions.append(
                        DocumentRegion(
                            _region_id(artifact.id, number, f"line-{line_number}", text),
                            artifact.id,
                            number,
                            "text",
                            f"page-{number}/line-{line_number}",
                            text,
                            bbox,
                        )
                    )
                if words and not _needs_hybrid_ocr(words, width, height):
                    continue
                diagnostics.append(
                    Diagnostic(
                        id=f"diagnostic-{canonical_hash((artifact.id, number, 'pdf_page_hybrid_ocr'))[:12]}",
                        scope="document",
                        code="pdf_page_hybrid_ocr",
                        message=f"第 {number} 页文本稀疏，已补充 OCR 识别",
                        source_id=artifact.id,
                    )
                )
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
                for line_number, item in enumerate(recognized or (), 1):
                    text, bbox = item[0], item[1]
                    confidence = float(item[2]) if len(item) > 2 else 0.8
                    ocr_region = DocumentRegion(
                        _region_id(artifact.id, number, f"ocr-{line_number}", text),
                        artifact.id,
                        number,
                        "ocr",
                        f"page-{number}/ocr-{line_number}",
                        text,
                        bbox,
                        confidence,
                    )
                    if not _is_duplicate_region(text, bbox, regions):
                        regions.append(ocr_region)
        finally:
            document.close()
        if not regions:
            raise AdapterFailure("PDF contains no readable text")
        return ParsedDocument(
            artifact=artifact,
            pages=tuple(pages),
            regions=tuple(regions),
            text="\n".join(region.text for region in regions),
            diagnostics=tuple(diagnostics),
        )


def parse_engineering_document(
    filename: str, content: bytes, *, ocr: OcrPort | None = None
) -> ParsedDocument:
    """Functional adapter entry point used by integrations and acceptance tests."""

    return LocalDocumentParser(ocr=ocr).parse(filename, content)
