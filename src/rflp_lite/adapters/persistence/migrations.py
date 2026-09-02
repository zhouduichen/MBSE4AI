"""Versioned SQLite schema migrations."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]


def _base_statements() -> tuple[str, ...]:
    tables = (
        "artifacts",
        "spans",
        "claims",
        "elements",
        "relations",
        "candidates",
        "simulations",
        "tasks",
        "evidence",
        "document_evidence",
        "trace_records",
        "domain_packs",
        "scheme_records",
        "indicator_envelopes",
        "layout_candidates",
        "discipline_evaluations",
        "optimization_runs",
        "concept_runs",
        "candidate_reviews",
        "workflow_runs",
    )

    return tuple(
        f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        for table in tables
    ) + (
        """
        CREATE TABLE IF NOT EXISTS baselines (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            hash TEXT NOT NULL UNIQUE,
            payload TEXT NOT NULL,
            sequence INTEGER NOT NULL UNIQUE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS workbench (
            id TEXT PRIMARY KEY,
            revision INTEGER NOT NULL DEFAULT 0,
            content_revision INTEGER NOT NULL DEFAULT 0,
            payload TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS workbench_revisions (
            revision INTEGER PRIMARY KEY,
            event TEXT NOT NULL,
            created_at TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS requirement_records (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            first_sequence INTEGER NOT NULL,
            last_sequence INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """,
    )


def _job_statements() -> tuple[str, ...]:
    return (
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            workspace TEXT NOT NULL,
            status TEXT NOT NULL,
            idempotency_key TEXT NOT NULL DEFAULT '',
            attempt INTEGER NOT NULL DEFAULT 0,
            lease_id TEXT NOT NULL DEFAULT '',
            lease_expires_at REAL NOT NULL DEFAULT 0,
            heartbeat_at REAL NOT NULL DEFAULT 0,
            snapshot_revision INTEGER NOT NULL DEFAULT 0,
            snapshot_content_revision INTEGER NOT NULL DEFAULT 0,
            input_hash TEXT NOT NULL DEFAULT '',
            payload TEXT NOT NULL,
            result TEXT,
            last_error TEXT,
            diagnostics TEXT NOT NULL DEFAULT '{}',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS job_blocks (
            job_id TEXT NOT NULL,
            block_id TEXT NOT NULL,
            status TEXT NOT NULL,
            attempt INTEGER NOT NULL DEFAULT 0,
            input_hash TEXT NOT NULL DEFAULT '',
            result TEXT,
            diagnostics TEXT NOT NULL DEFAULT '{}',
            updated_at REAL NOT NULL,
            PRIMARY KEY (job_id, block_id),
            FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_idempotency ON jobs(idempotency_key, status)",
    )


def _revision_columns(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(workbench)").fetchall()
    }


class MigrationRunner:
    """Apply ordered migrations atomically and verify schema invariants."""

    def __init__(
        self,
        path: Path,
        migrations: tuple[Migration, ...] | None = None,
    ) -> None:
        self.path = path
        self.migrations = migrations or (
            Migration(1, "base_schema", _base_statements()),
            Migration(2, "workbench_revision_columns", ()),
            Migration(3, "durable_jobs", _job_statements()),
            Migration(
                4,
                "job_runtime_metadata",
                (
                    "ALTER TABLE jobs ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'",
                ),
            ),
            Migration(
                5,
                "concept_workflow_runs",
                (
                    "CREATE TABLE IF NOT EXISTS workflow_runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)",
                ),
            ),
        )

    def _apply_migration(
        self, connection: sqlite3.Connection, migration: Migration
    ) -> None:
        for statement in migration.statements:
            connection.execute(statement)
        if migration.version == 2:
            self._ensure_workbench_revision_columns(connection)

    @staticmethod
    def _ensure_workbench_revision_columns(connection: sqlite3.Connection) -> None:
        columns = _revision_columns(connection)
        if "revision" not in columns:
            connection.execute(
                "ALTER TABLE workbench ADD COLUMN revision INTEGER NOT NULL DEFAULT 0"
            )
        if "content_revision" not in columns:
            connection.execute(
                "ALTER TABLE workbench ADD COLUMN content_revision INTEGER NOT NULL DEFAULT 0"
            )
        rows = connection.execute("SELECT id, payload FROM workbench").fetchall()
        for record_id, raw_payload in rows:
            try:
                payload = json.loads(raw_payload)
            except (TypeError, json.JSONDecodeError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            revision = int(payload.get("revision", 0) or 0)
            content_revision = int(
                payload.get("content_revision", revision) or 0
            )
            connection.execute(
                "UPDATE workbench SET revision = ?, content_revision = ? WHERE id = ?",
                (revision, content_revision, record_id),
            )

    @staticmethod
    def _verify_invariants(connection: sqlite3.Connection) -> None:
        required = {"id", "revision", "content_revision", "payload"}
        actual = _revision_columns(connection)
        missing = required - actual
        if missing:
            raise RuntimeError(f"workbench schema is missing columns: {sorted(missing)}")

    def upgrade(self, connection: sqlite3.Connection) -> int:
        """Upgrade the connection and return the resulting schema version."""
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        current_row = connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()
        current = int(current_row[0] if current_row else 0)
        for migration in sorted(self.migrations, key=lambda item: item.version):
            if migration.version <= current:
                continue
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._apply_migration(connection, migration)
                connection.execute(
                    """
                    INSERT INTO schema_migrations(version, name, applied_at)
                    VALUES (?, ?, ?)
                    """,
                    (
                        migration.version,
                        migration.name,
                        datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    ),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            current = migration.version
        self._verify_invariants(connection)
        return current


__all__ = ["Migration", "MigrationRunner"]
