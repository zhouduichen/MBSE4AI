"""Public document-format adapter primitives."""

from rflp_lite.adapters.documents.docx_reader import read_docx_text
from rflp_lite.adapters.documents.markdown_reader import read_markdown
from rflp_lite.adapters.documents.ocr import RapidOcrAdapter
from rflp_lite.adapters.documents.pdf_reader import open_pdf
from rflp_lite.adapters.documents.txt_reader import read_utf8_text

__all__ = [
    "RapidOcrAdapter",
    "open_pdf",
    "read_docx_text",
    "read_markdown",
    "read_utf8_text",
]
