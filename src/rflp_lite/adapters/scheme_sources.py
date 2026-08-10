"""Historical scheme source readers.

The concept-design workflow accepts a deliberately small interchange surface:
JSON and CSV uploads, plus an existing SQLite database opened in read-only
mode.  Readers return plain row dictionaries so application mapping remains
independent of the source format.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from pathlib import Path
from rflp_lite.domain.errors import AdapterFailure


_MAX_BYTES = 50 * 1024 * 1024
_MAX_ROWS = 50_000
_TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def _content_bytes(content: bytes | bytearray | memoryview | str) -> bytes:
    if isinstance(content, str):
        return content.encode("utf-8")
    if isinstance(content, (bytes, bytearray, memoryview)):
        return bytes(content)
    raise AdapterFailure("scheme source content must be bytes or text")


def _check_size(filename: str | Path, content: bytes) -> None:
    if not content:
        raise AdapterFailure(f"scheme source is empty: {filename}")
    if len(content) > _MAX_BYTES:
        raise AdapterFailure(f"scheme source exceeds 50 MiB: {filename}")


def _check_rows(rows: list[object], filename: str | Path) -> tuple[dict[str, object], ...]:
    if not rows:
        raise AdapterFailure(f"scheme source has no data rows: {filename}")
    if len(rows) > _MAX_ROWS:
        raise AdapterFailure(f"scheme source exceeds {_MAX_ROWS} rows: {filename}")
    result: list[dict[str, object]] = []
    for number, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise AdapterFailure(f"scheme row {number} must be an object: {filename}")
        # JSON object keys are strings.  SQLite can expose non-string column
        # names only for a malformed query, but normalising here makes all
        # reader outputs obey the same application contract.
        result.append({str(key): value for key, value in row.items()})
    return tuple(result)


def read_scheme_rows(
    filename: str | Path,
    content: bytes | bytearray | memoryview | str,
) -> tuple[dict[str, object], ...]:
    """Decode a JSON or CSV source into immutable-in-practice row objects.

    The function intentionally does not infer numbers in CSV.  CSV values are
    strings and are parsed against the domain-pack declaration by
    :func:`rflp_lite.application.scheme_library.import_scheme_rows`.
    """

    candidate = str(filename)
    raw = _content_bytes(content)
    _check_size(candidate, raw)
    suffix = Path(candidate).suffix.lower()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AdapterFailure(f"scheme source must be UTF-8: {candidate}") from exc

    if suffix == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AdapterFailure(f"scheme JSON is invalid: {candidate}") from exc
        if not isinstance(payload, list):
            raise AdapterFailure(f"scheme JSON must contain an array: {candidate}")
        return _check_rows(payload, candidate)

    if suffix == ".csv":
        try:
            reader = csv.DictReader(io.StringIO(text, newline=""))
            if reader.fieldnames is None or any(field is None or not field.strip() for field in reader.fieldnames):
                raise AdapterFailure(f"scheme CSV must contain a non-empty header: {candidate}")
            rows: list[dict[str, object]] = []
            for row in reader:
                if None in row:
                    raise AdapterFailure(f"scheme CSV has an unexpected extra column: {candidate}")
                rows.append(dict(row))
                if len(rows) > _MAX_ROWS:
                    raise AdapterFailure(f"scheme source exceeds {_MAX_ROWS} rows: {candidate}")
        except csv.Error as exc:
            raise AdapterFailure(f"scheme CSV is invalid: {candidate}") from exc
        if not rows:
            raise AdapterFailure(f"scheme CSV has no data rows: {candidate}")
        return tuple(rows)

    raise AdapterFailure("scheme source format must be .json or .csv")


def read_sqlite_scheme_rows(path: Path, table: str) -> tuple[dict[str, object], ...]:
    """Read a table from an existing SQLite database without write access."""

    candidate = Path(path)
    if not _TABLE_RE.fullmatch(table):
        raise AdapterFailure("SQLite scheme table name is invalid")
    try:
        connection = sqlite3.connect(f"file:{candidate.resolve()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise AdapterFailure(f"cannot open SQLite scheme source: {candidate}") from exc
    try:
        # The strict identifier allowlist above makes interpolation safe.  A
        # quoted identifier still protects names that happen to be keywords.
        cursor = connection.execute(f'SELECT * FROM "{table}"')
        columns = tuple(description[0] for description in cursor.description or ())
        rows: list[dict[str, object]] = []
        for values in cursor:
            rows.append({str(column): value for column, value in zip(columns, values)})
            if len(rows) > _MAX_ROWS:
                raise AdapterFailure(f"scheme source exceeds {_MAX_ROWS} rows: {candidate}")
        if not rows:
            raise AdapterFailure(f"SQLite scheme table is empty: {table}")
        return tuple(rows)
    except AdapterFailure:
        raise
    except sqlite3.Error as exc:
        raise AdapterFailure(f"cannot read SQLite scheme table {table!r}") from exc
    finally:
        connection.close()


__all__ = ["read_scheme_rows", "read_sqlite_scheme_rows"]
