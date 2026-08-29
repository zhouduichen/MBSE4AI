"""PDF library boundary for the document intelligence adapter."""

from __future__ import annotations

import io
from typing import Any

from rflp_lite.domain.errors import AdapterFailure


def open_pdf(content: bytes) -> Any:
    try:
        import pdfplumber
    except ImportError as exc:
        raise AdapterFailure(
            "PDF parsing is unavailable; install the 'documents' optional dependencies"
        ) from exc
    try:
        return pdfplumber.open(io.BytesIO(content))
    except Exception as exc:  # library-specific PDF parse errors vary by version
        raise AdapterFailure("invalid PDF document") from exc
