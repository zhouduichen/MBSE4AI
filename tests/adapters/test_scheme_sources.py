import sqlite3

import pytest

from rflp_lite.adapters.scheme_sources import read_scheme_rows, read_sqlite_scheme_rows
from rflp_lite.domain.errors import AdapterFailure


def test_csv_and_json_readers_return_row_objects():
    csv_rows = read_scheme_rows("schemes.csv", b"name,mass_kg\nA,120\n")
    json_rows = read_scheme_rows("schemes.json", b'[{"name":"B","mass_kg":130}]')
    assert csv_rows == ({"name": "A", "mass_kg": "120"},)
    assert json_rows == ({"mass_kg": 130, "name": "B"},)


def test_readers_reject_empty_or_wrong_shapes():
    with pytest.raises(AdapterFailure, match="empty"):
        read_scheme_rows("schemes.json", b"")
    with pytest.raises(AdapterFailure, match="array"):
        read_scheme_rows("schemes.json", b'{"name":"A"}')
    with pytest.raises(AdapterFailure, match="format"):
        read_scheme_rows("schemes.txt", b"name\nA\n")


def test_sqlite_reader_is_read_only_and_rejects_unsafe_table_name(tmp_path):
    source = tmp_path / "source.db"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE schemes(name TEXT, mass_kg REAL)")
    connection.execute("INSERT INTO schemes VALUES ('A', 120)")
    connection.commit()
    connection.close()

    assert read_sqlite_scheme_rows(source, "schemes") == (
        {"name": "A", "mass_kg": 120.0},
    )
    with pytest.raises(AdapterFailure, match="table"):
        read_sqlite_scheme_rows(source, "schemes; DROP TABLE schemes")
