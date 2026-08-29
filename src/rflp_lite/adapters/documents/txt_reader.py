"""UTF-8 text reader used by document and artifact adapters."""

from __future__ import annotations

from rflp_lite.domain.errors import AdapterFailure


def read_utf8_text(content: bytes, *, label: str = "artifact") -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AdapterFailure(f"{label} must be UTF-8 text") from exc
