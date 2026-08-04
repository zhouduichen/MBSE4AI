from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

from rflp_lite.domain.canonical import canonical_json
from rflp_lite.domain.models import (
    Artifact,
    Baseline,
    Candidate,
    Claim,
    Evidence,
    ModelElement,
    Relation,
    SimulationRun,
    TaskContract,
)


class SQLiteRepository:
    _TABLES = (
        "artifacts",
        "claims",
        "elements",
        "candidates",
        "simulations",
        "tasks",
        "evidence",
    )

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._connection = sqlite3.connect(path, isolation_level=None)
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    def close(self) -> None:
        self._connection.close()

    def _create_schema(self) -> None:
        for table in self._TABLES:
            self._connection.execute(
                f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS baselines (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                hash TEXT NOT NULL UNIQUE,
                payload TEXT NOT NULL,
                sequence INTEGER NOT NULL UNIQUE
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )

    @contextmanager
    def transaction(self):
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._connection.execute("ROLLBACK")
            raise
        else:
            self._connection.execute("COMMIT")

    def _save_many(self, table: str, values: Iterable[object]) -> None:
        rows = [(getattr(value, "id"), canonical_json(value)) for value in values]
        self._connection.executemany(
            f"INSERT OR REPLACE INTO {table}(id, payload) VALUES (?, ?)", rows
        )

    def save_artifacts(self, values: tuple[Artifact, ...]) -> None:
        self._save_many("artifacts", values)

    def save_claims(self, values: tuple[Claim, ...]) -> None:
        self._save_many("claims", values)

    def save_elements(self, values: tuple[ModelElement, ...]) -> None:
        self._save_many("elements", values)

    def save_candidates(self, values: tuple[Candidate, ...]) -> None:
        self._save_many("candidates", values)

    def save_simulation(self, value: SimulationRun) -> None:
        self._save_many("simulations", (value,))

    def save_baseline(self, value: Baseline) -> Baseline:
        next_sequence = self._connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM baselines"
        ).fetchone()[0]
        self._connection.execute(
            """
            INSERT OR IGNORE INTO baselines(id, status, hash, payload, sequence)
            VALUES (?, ?, ?, ?, ?)
            """,
            (value.id, value.status, value.hash, canonical_json(value), next_sequence),
        )
        return value

    def save_tasks(self, values: tuple[TaskContract, ...]) -> None:
        self._save_many("tasks", values)

    def save_evidence(self, values: tuple[Evidence, ...]) -> None:
        self._save_many("evidence", values)

    def latest_baseline(self) -> Baseline | None:
        row = self._connection.execute(
            "SELECT payload FROM baselines ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        value = json.loads(row[0])
        elements = tuple(ModelElement(**element) for element in value["elements"])
        relations = tuple(Relation(**relation) for relation in value["relations"])
        payload = (
            ("elements", elements),
            ("relations", relations),
        )
        return Baseline(
            id=value["id"],
            status=value["status"],
            elements=elements,
            relations=relations,
            payload=payload,
            hash=value["hash"],
        )

    def record_audit(self, kind: str, payload: dict[str, object]) -> None:
        self._connection.execute(
            "INSERT INTO audit_events(kind, payload) VALUES (?, ?)",
            (kind, canonical_json(payload)),
        )

    def audit_events(self, kind: str | None = None) -> tuple[dict[str, object], ...]:
        if kind is None:
            rows = self._connection.execute(
                "SELECT kind, payload FROM audit_events ORDER BY sequence"
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT kind, payload FROM audit_events WHERE kind = ? ORDER BY sequence",
                (kind,),
            ).fetchall()
        return tuple({"kind": row[0], "payload": json.loads(row[1])} for row in rows)

