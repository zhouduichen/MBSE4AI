"""Normalize sentence-sized requirement inputs without rewriting their meaning."""

from __future__ import annotations

import re


_SEPARATOR = re.compile(r"(?:\r?\n+|[；;。！？!?]+|(?<=[.!?])\s+(?=[A-Z]))")
_LIST_PREFIX = re.compile(
    r"^\s*(?:(?:[-*•])\s*|\d+[.)、]\s*|[（(][一二三四五六七八九十\d]+[）)]\s*)"
)


def split_requirement_statements(text: str) -> tuple[str, ...]:
    """Return ordered, normalized requirement-sized statements from ``text``."""

    values: list[str] = []
    seen: set[str] = set()
    for raw in _SEPARATOR.split(str(text or "")):
        value = _LIST_PREFIX.sub("", raw)
        value = " ".join(value.split()).strip().rstrip("。；;！？!?.")
        if value and value not in seen:
            seen.add(value)
            values.append(value)
    return tuple(values)
