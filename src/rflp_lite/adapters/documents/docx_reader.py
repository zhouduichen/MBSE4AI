"""DOCX text and table reader."""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree

from rflp_lite.domain.errors import AdapterFailure


_WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def read_docx_text(content: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
    except (KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise AdapterFailure("invalid DOCX document") from exc
    namespace = _WORD_NAMESPACE
    table_paragraph_ids: set[int] = set()
    rows: list[str] = []
    for table in root.iter(f"{namespace}tbl"):
        for table_row in table.iter(f"{namespace}tr"):
            cells = [
                " ".join(
                    "".join(node.text or "" for node in paragraph.iter(f"{namespace}t"))
                    for paragraph in cell.iter(f"{namespace}p")
                ).strip()
                for cell in table_row.iter(f"{namespace}tc")
            ]
            row_text = " | ".join(cell for cell in cells if cell)
            if row_text:
                rows.append(row_text)
        for paragraph in table.iter(f"{namespace}p"):
            table_paragraph_ids.add(id(paragraph))
    paragraphs = []
    for paragraph in root.iter(f"{namespace}p"):
        if id(paragraph) in table_paragraph_ids:
            continue
        text = "".join(
            node.text or "" for node in paragraph.iter(f"{namespace}t")
        ).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs + rows)
