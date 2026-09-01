"""DOCX text and table reader."""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree

from rflp_lite.domain.errors import AdapterFailure


_WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass(frozen=True, slots=True)
class DocxBlock:
    """A document block with enough layout context for requirement evidence."""

    kind: str
    locator: str
    text: str
    heading_path: tuple[str, ...] = ()
    table_id: str = ""
    row_index: int | None = None
    column_index: int | None = None


def _paragraph_text(paragraph: ElementTree.Element) -> str:
    return "".join(
        node.text or "" for node in paragraph.iter(f"{_WORD_NAMESPACE}t")
    ).strip()


def read_docx_blocks(content: bytes) -> tuple[DocxBlock, ...]:
    """Read DOCX body blocks while retaining heading and table coordinates."""

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
    except (KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise AdapterFailure("invalid DOCX document") from exc
    body = root.find(f"{_WORD_NAMESPACE}body")
    if body is None:
        return ()

    heading_path: list[str] = []
    blocks: list[DocxBlock] = []
    paragraph_index = 0
    table_index = 0
    for child in body:
        if child.tag == f"{_WORD_NAMESPACE}p":
            paragraph_index += 1
            text = _paragraph_text(child)
            if not text:
                continue
            style = child.find(f"{_WORD_NAMESPACE}pPr/{_WORD_NAMESPACE}pStyle")
            style_id = style.get(f"{_WORD_NAMESPACE}val", "") if style is not None else ""
            match = re.fullmatch(r"(?:Heading|标题)\s*([1-9])", style_id, re.IGNORECASE)
            if match:
                level = int(match.group(1))
                del heading_path[level - 1 :]
                heading_path.append(text)
                kind = "heading"
            else:
                kind = "paragraph"
            blocks.append(
                DocxBlock(kind, f"paragraph-{paragraph_index}", text, tuple(heading_path))
            )
            continue
        if child.tag != f"{_WORD_NAMESPACE}tbl":
            continue
        table_index += 1
        table_id = f"table-{table_index}"
        for row_index, row in enumerate(child.findall(f"{_WORD_NAMESPACE}tr"), 1):
            for column_index, cell in enumerate(row.findall(f"{_WORD_NAMESPACE}tc"), 1):
                text = " ".join(
                    _paragraph_text(paragraph)
                    for paragraph in cell.iter(f"{_WORD_NAMESPACE}p")
                ).strip()
                if not text:
                    continue
                blocks.append(
                    DocxBlock(
                        "table_cell",
                        f"{table_id}/r{row_index}/c{column_index}",
                        text,
                        tuple(heading_path),
                        table_id,
                        row_index,
                        column_index,
                    )
                )
    return tuple(blocks)


def read_docx_text(content: bytes) -> str:
    """Return the historical flattened text projection for old callers.

    The structured parser exposes one block per table cell.  Existing upload
    and artifact readers expect one row per table, however, so this function
    deliberately keeps that legacy projection (paragraphs first, then rows
    joined with `` | ``).
    """

    blocks = read_docx_blocks(content)
    paragraphs = [block.text for block in blocks if block.kind != "table_cell"]
    rows: dict[tuple[str, int], dict[int, str]] = {}
    row_order: list[tuple[str, int]] = []
    for block in blocks:
        if block.kind != "table_cell" or block.row_index is None:
            continue
        key = (block.table_id, block.row_index)
        if key not in rows:
            rows[key] = {}
            row_order.append(key)
        rows[key][block.column_index or 0] = block.text
    table_rows = [
        " | ".join(rows[key][column] for column in sorted(rows[key]) if rows[key][column])
        for key in row_order
    ]
    return "\n".join(paragraphs + [row for row in table_rows if row])
