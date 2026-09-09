"""Small, deterministic SQLite schema for Repository v2."""

from __future__ import annotations

import sqlite3


V2_SCHEMA_VERSION = 2


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone() is not None


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(f'PRAGMA table_info("{table_name}")')
    }


def _preserve_incompatible_tables(connection: sqlite3.Connection) -> None:
    """Keep legacy tables intact before creating same-named v2 tables."""

    contracts = {
        "relations": {"id", "project_id", "source_id", "predicate", "target_id"},
        "evidence": {"id", "project_id", "source_type", "claim", "excerpt"},
        "audit_events": {"sequence", "project_id", "kind", "payload"},
    }
    for table_name, required_columns in contracts.items():
        if not _table_exists(connection, table_name):
            continue
        if required_columns <= _table_columns(connection, table_name):
            continue
        legacy_name = f"legacy_{table_name}"
        suffix = 1
        while _table_exists(connection, legacy_name):
            suffix += 1
            legacy_name = f"legacy_{table_name}_{suffix}"
        connection.execute(
            f'ALTER TABLE "{table_name}" RENAME TO "{legacy_name}"'
        )


def _apply_core_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations_v2 (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 0,
            content_revision INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            settings_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            path TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL DEFAULT '',
            sha256 TEXT NOT NULL DEFAULT '',
            metadata TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS source_regions (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            page INTEGER,
            locator TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL,
            bbox TEXT NOT NULL DEFAULT '[]',
            heading_path TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS entities (
            id TEXT NOT NULL,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            lifecycle_hint TEXT NOT NULL DEFAULT '[]',
            producer TEXT NOT NULL,
            confidence REAL,
            payload_json TEXT NOT NULL,
            source_ids TEXT NOT NULL DEFAULT '[]',
            evidence_ids TEXT NOT NULL DEFAULT '[]',
            created_revision INTEGER NOT NULL,
            updated_revision INTEGER NOT NULL,
            PRIMARY KEY (project_id, id)
        );
        CREATE TABLE IF NOT EXISTS relations (
            id TEXT NOT NULL,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            source_id TEXT NOT NULL,
            predicate TEXT NOT NULL,
            target_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'accepted',
            evidence_ids TEXT NOT NULL DEFAULT '[]',
            created_revision INTEGER NOT NULL,
            PRIMARY KEY (project_id, id)
        );
        CREATE TABLE IF NOT EXISTS evidence (
            id TEXT NOT NULL,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL DEFAULT '',
            locator TEXT NOT NULL DEFAULT '',
            claim TEXT NOT NULL DEFAULT '',
            excerpt TEXT NOT NULL DEFAULT '',
            authority REAL,
            relevance REAL,
            PRIMARY KEY (project_id, id)
        );
        CREATE TABLE IF NOT EXISTS revisions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            sequence INTEGER NOT NULL,
            parent_id TEXT,
            reason TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            snapshot_hash TEXT NOT NULL,
            run_id TEXT,
            UNIQUE(project_id, sequence)
        );
        CREATE TABLE IF NOT EXISTS issues (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            run_id TEXT,
            task_id TEXT,
            code TEXT NOT NULL,
            severity TEXT NOT NULL,
            entity_ids TEXT NOT NULL DEFAULT '[]',
            suggested_rollback TEXT,
            status TEXT NOT NULL DEFAULT 'open'
        );
        CREATE TABLE IF NOT EXISTS audit_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_entities_project_kind ON entities(project_id, kind);
        CREATE INDEX IF NOT EXISTS idx_relations_project_predicate ON relations(project_id, predicate);
        CREATE INDEX IF NOT EXISTS idx_revisions_project_sequence ON revisions(project_id, sequence);
        INSERT OR REPLACE INTO schema_migrations_v2(version, name) VALUES (2, 'model_graph_and_run_ledger');
        """
    )
    _apply_ledger_schema(connection)
    _ensure_columns(connection, "runs", {
        "provider_id": "TEXT NOT NULL DEFAULT ''", "model_id": "TEXT NOT NULL DEFAULT ''",
        "execution_mode": "TEXT NOT NULL DEFAULT ''", "context_hash": "TEXT NOT NULL DEFAULT ''",
        "task_spec_hash": "TEXT NOT NULL DEFAULT ''", "prompt_hash": "TEXT NOT NULL DEFAULT ''",
        "output_hash": "TEXT NOT NULL DEFAULT ''", "started_at": "REAL NOT NULL DEFAULT 0",
        "completed_at": "REAL NOT NULL DEFAULT 0",
    })
    _ensure_columns(connection, "steps", {
        "output_hash": "TEXT NOT NULL DEFAULT ''", "provider_id": "TEXT NOT NULL DEFAULT ''",
        "model_id": "TEXT NOT NULL DEFAULT ''", "prompt_template_id": "TEXT NOT NULL DEFAULT ''",
        "prompt_version": "TEXT NOT NULL DEFAULT ''", "prompt_hash": "TEXT NOT NULL DEFAULT ''",
        "context_hash": "TEXT NOT NULL DEFAULT ''", "started_at": "REAL NOT NULL DEFAULT 0",
        "completed_at": "REAL NOT NULL DEFAULT 0",
    })
    _ensure_columns(connection, "patches", {
        "input_hash": "TEXT NOT NULL DEFAULT ''", "output_hash": "TEXT NOT NULL DEFAULT ''",
        "provider_id": "TEXT NOT NULL DEFAULT ''", "model_id": "TEXT NOT NULL DEFAULT ''",
    })


def _apply_ledger_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            phase TEXT NOT NULL, status TEXT NOT NULL, lease TEXT NOT NULL DEFAULT '', heartbeat REAL NOT NULL DEFAULT 0,
            attempt INTEGER NOT NULL DEFAULT 0, methodology_version TEXT NOT NULL,
            model_profile TEXT NOT NULL DEFAULT '', input_hash TEXT NOT NULL DEFAULT '', diagnostics TEXT NOT NULL DEFAULT '[]',
            provider_id TEXT NOT NULL DEFAULT '', model_id TEXT NOT NULL DEFAULT '', execution_mode TEXT NOT NULL DEFAULT '',
            context_hash TEXT NOT NULL DEFAULT '', task_spec_hash TEXT NOT NULL DEFAULT '', prompt_hash TEXT NOT NULL DEFAULT '',
            output_hash TEXT NOT NULL DEFAULT '', started_at REAL NOT NULL DEFAULT 0, completed_at REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS steps (
            run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE, task_id TEXT NOT NULL, status TEXT NOT NULL,
            attempt INTEGER NOT NULL DEFAULT 0, input_hash TEXT NOT NULL DEFAULT '', output_patch_id TEXT,
            diagnostics TEXT NOT NULL DEFAULT '[]', output_hash TEXT NOT NULL DEFAULT '', provider_id TEXT NOT NULL DEFAULT '',
            model_id TEXT NOT NULL DEFAULT '', prompt_template_id TEXT NOT NULL DEFAULT '', context_hash TEXT NOT NULL DEFAULT '',
            started_at REAL NOT NULL DEFAULT 0, completed_at REAL NOT NULL DEFAULT 0, PRIMARY KEY (run_id, task_id)
        );
        CREATE TABLE IF NOT EXISTS patches (
            id TEXT PRIMARY KEY, run_id TEXT REFERENCES runs(id) ON DELETE CASCADE, task_id TEXT NOT NULL,
            operations_json TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL,
            input_hash TEXT NOT NULL DEFAULT '', output_hash TEXT NOT NULL DEFAULT '', provider_id TEXT NOT NULL DEFAULT '', model_id TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS closures (
            project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE, run_id TEXT NOT NULL, revision INTEGER NOT NULL,
            manifest_json TEXT NOT NULL, gate_snapshot_json TEXT NOT NULL, audit_summary_json TEXT NOT NULL, created_at REAL NOT NULL
        );
        """
    )


def _ensure_columns(connection: sqlite3.Connection, table_name: str, columns: dict[str, str]) -> None:
    present = _table_columns(connection, table_name)
    for name, definition in columns.items():
        if name not in present:
            connection.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{name}" {definition}')
def _apply_search_schema(connection: sqlite3.Connection) -> None:
    """Create rebuildable FTS indexes, with a portable SQLite fallback."""

    definitions = (
        ("source_regions_fts", "project_id UNINDEXED, region_id UNINDEXED, text, locator, heading_path", "project_id TEXT, region_id TEXT, text TEXT, locator TEXT, heading_path TEXT"),
        ("entities_fts", "project_id UNINDEXED, entity_id UNINDEXED, name, payload", "project_id TEXT, entity_id TEXT, name TEXT, payload TEXT"),
        ("evidence_fts", "project_id UNINDEXED, evidence_id UNINDEXED, claim, excerpt", "project_id TEXT, evidence_id TEXT, claim TEXT, excerpt TEXT"),
    )
    for table, columns, fallback_columns in definitions:
        statement = f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} USING fts5({columns})"
        try:
            connection.execute(statement)
        except sqlite3.OperationalError:
            connection.execute(f"CREATE TABLE IF NOT EXISTS {table} ({fallback_columns})")


def apply_v2_schema(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    _preserve_incompatible_tables(connection)
    _apply_core_schema(connection)
    _apply_search_schema(connection)
