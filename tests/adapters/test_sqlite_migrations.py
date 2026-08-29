from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from rflp_lite.adapters.persistence.migrations import Migration, MigrationRunner
from rflp_lite.adapters.sqlite_repository import SQLiteRepository


def test_fresh_and_repeated_migrations_are_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "model.db"
    first = SQLiteRepository(path)
    first.close()
    second = SQLiteRepository(path)
    versions = second._connection.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall()
    columns = second._connection.execute("PRAGMA table_info(workbench)").fetchall()
    second.close()

    assert versions == [(1,), (2,)]
    assert {row[1] for row in columns} >= {
        "revision",
        "content_revision",
        "payload",
    }


def test_legacy_workbench_payload_is_backfilled_during_migration(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE workbench (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
    connection.execute(
        "INSERT INTO workbench(id, payload) VALUES ('current', ?)",
        ('{"revision": 7, "claims": []}',),
    )
    connection.commit()
    connection.close()

    repository = SQLiteRepository(path)
    assert repository.load_workbench() == {
        "revision": 7,
        "claims": [],
    }
    row = repository._connection.execute(
        "SELECT revision, content_revision FROM workbench WHERE id = 'current'"
    ).fetchone()
    repository.close()

    assert row == (7, 7)


def test_failed_migration_rolls_back_its_ddl(tmp_path: Path) -> None:
    path = tmp_path / "broken.db"
    connection = sqlite3.connect(path, isolation_level=None)
    runner = MigrationRunner(
        path,
        migrations=(Migration(1, "broken", ("CREATE TABLE transient (id INTEGER)",)),),
    )

    def fail_after_ddl(conn: sqlite3.Connection, migration: Migration) -> None:
        conn.execute(migration.statements[0])
        raise RuntimeError("injected migration failure")

    runner._apply_migration = fail_after_ddl  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="injected"):
        runner.upgrade(connection)

    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'transient'"
    ).fetchone() is None
    connection.close()
