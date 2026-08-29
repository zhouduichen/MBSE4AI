"""SQLite-backed durable job repository."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

from rflp_lite.adapters.persistence.migrations import MigrationRunner
from rflp_lite.domain.canonical import canonical_json
from rflp_lite.ports.jobs import ACTIVE_JOB_STATUSES


def _decode(value: str | None, default: object) -> object:
    if value is None:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


class SQLiteJobRepository:
    def __init__(self, database_path: Path, *, lease_seconds: float = 30.0) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.path = database_path
        self.lease_seconds = max(1.0, float(lease_seconds))
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            database_path, isolation_level=None, check_same_thread=False
        )
        self._connection.execute("PRAGMA foreign_keys = ON")
        MigrationRunner(database_path).upgrade(self._connection)

    def close(self) -> None:
        self._connection.close()

    def import_legacy_file(self, source: Path, archived: Path) -> int:
        """Import legacy jobs once, renaming the source only after verification."""
        if not source.is_file() or archived.exists():
            return 0
        raw = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
            raise ValueError("jobs.json must contain a list of objects")
        with self._transaction():
            for item in raw:
                self._import_record(item)
            expected_ids = {str(item.get("id", "")) for item in raw}
            actual_ids = {
                str(row[0])
                for row in self._connection.execute("SELECT id FROM jobs").fetchall()
            }
            if not expected_ids <= actual_ids:
                raise RuntimeError("legacy job import verification failed")
        archived.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, archived)
        return len(raw)

    def _import_record(self, item: Mapping[str, object]) -> None:
        job_id = str(item.get("id", "")).strip()
        if not job_id:
            raise ValueError("legacy job is missing id")
        status = str(item.get("status", "queued"))
        if status == "completed":
            status = "succeeded"
        if status not in {
            "queued",
            "running",
            "succeeded",
            "degraded",
            "failed",
            "interrupted",
            "superseded",
            "cancelled",
        }:
            raise ValueError(f"unknown legacy job status: {status}")
        payload = item.get("payload", {})
        payload_dict = payload if isinstance(payload, dict) else {}
        now = time.time()
        self._connection.execute(
            """
            INSERT OR IGNORE INTO jobs(
                id, kind, workspace, status, idempotency_key, attempt,
                lease_id, lease_expires_at, heartbeat_at,
                snapshot_revision, snapshot_content_revision, input_hash,
                payload, result, last_error, diagnostics, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                str(item.get("kind", "legacy")),
                str(payload_dict.get("workspace", item.get("workspace", ""))),
                status,
                str(item.get("idempotency_key", "")),
                int(item.get("attempt", 0) or 0),
                str(item.get("lease_id", "")),
                float(item.get("lease_expires_at", 0.0) or 0.0),
                float(item.get("heartbeat_at", 0.0) or 0.0),
                int(payload_dict.get("snapshot_revision", 0) or 0),
                int(payload_dict.get("snapshot_content_revision", 0) or 0),
                str(payload_dict.get("input_hash", item.get("input_hash", ""))),
                canonical_json(payload_dict),
                None if item.get("result") is None else canonical_json(item["result"]),
                None if item.get("last_error") is None else canonical_json(item["last_error"]),
                canonical_json(item.get("diagnostics", {})),
                now,
                now,
            ),
        )
        blocks = item.get("block_states", item.get("blocks", {}))
        if isinstance(blocks, dict):
            for block_id, block_status in blocks.items():
                self._connection.execute(
                    """
                    INSERT OR IGNORE INTO job_blocks(
                        job_id, block_id, status, attempt, input_hash, diagnostics, updated_at
                    ) VALUES (?, ?, ?, ?, ?, '{}', ?)
                    """,
                    (
                        job_id,
                        str(block_id),
                        str(block_status),
                        int(item.get("attempt", 0) or 0),
                        str(payload_dict.get("input_hash", "")),
                        now,
                    ),
                )

    def _transaction(self):
        class _Transaction:
            def __init__(self, repository: SQLiteJobRepository) -> None:
                self.repository = repository

            def __enter__(self):
                self.repository._lock.acquire()
                self.repository._connection.execute("BEGIN IMMEDIATE")
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                try:
                    if exc_type is None:
                        self.repository._connection.commit()
                    else:
                        self.repository._connection.rollback()
                finally:
                    self.repository._lock.release()
                return False

        return _Transaction(self)

    def _record(self, row: sqlite3.Row | tuple[object, ...]) -> dict[str, object]:
        (
            job_id,
            kind,
            workspace,
            status,
            idempotency_key,
            attempt,
            lease_id,
            lease_expires_at,
            heartbeat_at,
            snapshot_revision,
            snapshot_content_revision,
            input_hash,
            payload,
            result,
            last_error,
            diagnostics,
            created_at,
            updated_at,
        ) = row
        decoded_payload = _decode(str(payload), {})
        payload_dict = decoded_payload if isinstance(decoded_payload, dict) else {}
        block_rows = self._connection.execute(
            "SELECT block_id, status FROM job_blocks WHERE job_id = ? ORDER BY block_id",
            (str(job_id),),
        ).fetchall()
        states = {str(block_id): str(block_status) for block_id, block_status in block_rows}
        blocks = payload_dict.get("blocks", {})
        if not isinstance(blocks, dict):
            blocks = {}
        effective_blocks = states or dict(blocks)
        record: dict[str, object] = {
            "id": str(job_id),
            "kind": str(kind),
            "workspace": str(workspace),
            "payload": payload_dict,
            "status": str(status),
            "attempt": int(attempt),
            "lease_id": str(lease_id),
            "lease_expires_at": float(lease_expires_at),
            "heartbeat_at": float(heartbeat_at),
            "snapshot_revision": int(snapshot_revision),
            "snapshot_content_revision": int(snapshot_content_revision),
            "input_hash": str(input_hash),
            "last_error": _decode(str(last_error) if last_error is not None else None, None),
            "diagnostics": _decode(str(diagnostics), {}),
            "blocks": effective_blocks,
            "block_states": effective_blocks,
            "idempotency_key": str(idempotency_key),
            "created_at": float(created_at),
            "updated_at": float(updated_at),
        }
        if result is not None:
            record["result"] = _decode(str(result), {})
        if record["last_error"] is not None:
            record["error"] = record["last_error"]
        return record

    def _find(self, job_id: str) -> dict[str, object] | None:
        row = self._connection.execute(
            """
            SELECT id, kind, workspace, status, idempotency_key, attempt,
                   lease_id, lease_expires_at, heartbeat_at, snapshot_revision,
                   snapshot_content_revision, input_hash, payload, result,
                   last_error, diagnostics, created_at, updated_at
            FROM jobs WHERE id = ?
            """,
            (str(job_id),),
        ).fetchone()
        return self._record(row) if row is not None else None

    def submit(self, kind: str, payload: Mapping[str, object]) -> dict[str, object]:
        payload_dict = json.loads(canonical_json(dict(payload)))
        key = str(payload_dict.get("idempotency_key", "")).strip()
        with self._transaction():
            if key:
                existing = self._connection.execute(
                    """
                    SELECT id FROM jobs
                    WHERE idempotency_key = ? AND status IN ('queued', 'running')
                    ORDER BY created_at LIMIT 1
                    """,
                    (key,),
                ).fetchone()
                if existing is not None:
                    return self._find(str(existing[0])) or {}
            now = time.time()
            job_id = f"job-{uuid4().hex[:12]}"
            blocks = payload_dict.get("blocks", {})
            block_map = blocks if isinstance(blocks, dict) else {}
            self._connection.execute(
                """
                INSERT INTO jobs(
                    id, kind, workspace, status, idempotency_key, payload,
                    snapshot_revision, snapshot_content_revision, input_hash,
                    diagnostics, created_at, updated_at
                ) VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?, '{}', ?, ?)
                """,
                (
                    job_id,
                    str(kind),
                    str(payload_dict.get("workspace", "")),
                    key,
                    canonical_json(payload_dict),
                    int(payload_dict.get("snapshot_revision", 0) or 0),
                    int(payload_dict.get("snapshot_content_revision", 0) or 0),
                    str(payload_dict.get("input_hash", "")),
                    now,
                    now,
                ),
            )
            for block_id, status in block_map.items():
                self._connection.execute(
                    """
                    INSERT INTO job_blocks(job_id, block_id, status, input_hash, diagnostics, updated_at)
                    VALUES (?, ?, ?, ?, '{}', ?)
                    """,
                    (job_id, str(block_id), str(status), str(payload_dict.get("input_hash", "")), now),
                )
            return self._find(job_id) or {}

    def get(self, job_id: str) -> dict[str, object] | None:
        with self._lock:
            return self._find(job_id)

    def list(self) -> tuple[dict[str, object], ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT id FROM jobs ORDER BY created_at, id"
            ).fetchall()
            records: list[dict[str, object]] = []
            for row in rows:
                record = self._find(str(row[0]))
                if record is not None:
                    records.append(record)
            return tuple(records)

    def update(self, job_id: str, patch: Mapping[str, object]) -> dict[str, object] | None:
        normalized = json.loads(canonical_json(dict(patch)))
        allowed = {
            "status",
            "attempt",
            "lease_id",
            "lease_expires_at",
            "heartbeat_at",
            "input_hash",
            "last_error",
            "result",
            "diagnostics",
        }
        with self._transaction():
            current = self._find(job_id)
            if current is None:
                return None
            values: dict[str, object] = {}
            for key in allowed:
                if key in normalized:
                    values[key] = normalized[key]
            if "error" in normalized and "last_error" not in values:
                values["last_error"] = normalized["error"]
            now = time.time()
            assignments = ["updated_at = ?"]
            params: list[object] = [now]
            columns = {
                "status": "status",
                "attempt": "attempt",
                "lease_id": "lease_id",
                "lease_expires_at": "lease_expires_at",
                "heartbeat_at": "heartbeat_at",
                "input_hash": "input_hash",
            }
            for key, column in columns.items():
                if key in values:
                    assignments.append(f"{column} = ?")
                    params.append(values[key])
            for key, column in (("last_error", "last_error"), ("result", "result"), ("diagnostics", "diagnostics")):
                if key in values:
                    assignments.append(f"{column} = ?")
                    params.append(None if values[key] is None else canonical_json(values[key]))
            params.append(str(job_id))
            self._connection.execute(
                f"UPDATE jobs SET {', '.join(assignments)} WHERE id = ?", params
            )
            block_updates = normalized.get("block_states", normalized.get("blocks", {}))
            if isinstance(block_updates, dict):
                for block_id, value in block_updates.items():
                    block_patch = value if isinstance(value, dict) else {"status": value}
                    assignments = ["updated_at = ?"]
                    block_params: list[object] = [now]
                    for key, column in (
                        ("status", "status"),
                        ("attempt", "attempt"),
                        ("input_hash", "input_hash"),
                    ):
                        if key in block_patch:
                            assignments.append(f"{column} = ?")
                            block_params.append(block_patch[key])
                    for key, column in (("result", "result"), ("diagnostics", "diagnostics")):
                        if key in block_patch:
                            assignments.append(f"{column} = ?")
                            block_params.append(
                                None
                                if block_patch[key] is None
                                else canonical_json(block_patch[key])
                            )
                    block_params.extend((str(job_id), str(block_id)))
                    self._connection.execute(
                        f"UPDATE job_blocks SET {', '.join(assignments)} "
                        "WHERE job_id = ? AND block_id = ?",
                        block_params,
                    )
            return self._find(job_id)

    def recover_startup(self, now: float | None = None) -> tuple[dict[str, object], ...]:
        current_time = time.time() if now is None else float(now)
        with self._transaction():
            rows = self._connection.execute(
                "SELECT id FROM jobs WHERE status = 'running' AND lease_expires_at <= ?",
                (current_time,),
            ).fetchall()
            for row in rows:
                self._connection.execute(
                    "UPDATE jobs SET status = 'interrupted', last_error = ?, updated_at = ? WHERE id = ?",
                    (
                        canonical_json({"type": "StartupRecovery", "message": "进程重启后未发现有效 lease"}),
                        current_time,
                        str(row[0]),
                    ),
                )
                self._connection.execute(
                    "UPDATE job_blocks SET status = 'interrupted', updated_at = ? WHERE job_id = ? AND status = 'running'",
                    (current_time, str(row[0])),
                )
            return tuple(self._find(str(row[0])) for row in rows if self._find(str(row[0])))

    def heartbeat(self, job_id: str, lease_id: str, now: float | None = None) -> dict[str, object] | None:
        current_time = time.time() if now is None else float(now)
        with self._transaction():
            current = self._find(job_id)
            if (
                current is None
                or current.get("status") != "running"
                or str(current.get("lease_id", "")) != str(lease_id)
                or float(current.get("lease_expires_at", 0.0) or 0.0) <= current_time
            ):
                return None
            self._connection.execute(
                "UPDATE jobs SET heartbeat_at = ?, lease_expires_at = ?, updated_at = ? WHERE id = ?",
                (current_time, current_time + self.lease_seconds, current_time, str(job_id)),
            )
            return self._find(job_id)
