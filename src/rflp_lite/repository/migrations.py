"""Small, deterministic SQLite schema for Repository v2."""

from __future__ import annotations

import sqlite3


V2_SCHEMA_VERSION = 2


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
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            phase TEXT NOT NULL,
            status TEXT NOT NULL,
            lease TEXT NOT NULL DEFAULT '',
            heartbeat REAL NOT NULL DEFAULT 0,
            attempt INTEGER NOT NULL DEFAULT 0,
            methodology_version TEXT NOT NULL,
            model_profile TEXT NOT NULL DEFAULT '',
            input_hash TEXT NOT NULL DEFAULT '',
            diagnostics TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS steps (
            run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            task_id TEXT NOT NULL,
            status TEXT NOT NULL,
            attempt INTEGER NOT NULL DEFAULT 0,
            input_hash TEXT NOT NULL DEFAULT '',
            output_patch_id TEXT,
            diagnostics TEXT NOT NULL DEFAULT '[]',
            PRIMARY KEY (run_id, task_id)
        );
        CREATE TABLE IF NOT EXISTS patches (
            id TEXT PRIMARY KEY,
            run_id TEXT REFERENCES runs(id) ON DELETE CASCADE,
            task_id TEXT NOT NULL,
            operations_json TEXT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL
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
    _apply_core_schema(connection)
    _apply_search_schema(connection)
