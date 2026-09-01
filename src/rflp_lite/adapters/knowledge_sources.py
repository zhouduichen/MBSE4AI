"""Safe JSON/CSV/SQLite readers for versioned knowledge datasets."""

from __future__ import annotations

from pathlib import Path

from rflp_lite.adapters.scheme_sources import read_scheme_rows, read_sqlite_scheme_rows


def read_knowledge_rows(filename: str | Path, content: bytes | bytearray | memoryview | str):
    return read_scheme_rows(filename, content)


def read_sqlite_knowledge_rows(path: Path, table: str):
    return read_sqlite_scheme_rows(path, table)


__all__ = ["read_knowledge_rows", "read_sqlite_knowledge_rows"]
