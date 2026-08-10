from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Mapping
from typing import Iterable

from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import ContractViolation
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
    TextSpan,
)


class SQLiteRepository:
    _TABLES = (
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
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS workbench (
                id TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS requirement_records (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                first_sequence INTEGER NOT NULL,
                last_sequence INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
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

    def save_spans(self, values: tuple[TextSpan, ...]) -> None:
        self._save_many("spans", values)

    def save_claims(self, values: tuple[Claim, ...]) -> None:
        self._save_many("claims", values)

    def save_elements(self, values: tuple[ModelElement, ...]) -> None:
        self._save_many("elements", values)

    def save_relations(self, values: tuple[Relation, ...]) -> None:
        self._save_many("relations", values)

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

    def save_document_evidence(self, values: tuple[dict[str, object], ...]) -> None:
        self._save_payloads("document_evidence", values)

    def save_trace_records(self, values: tuple[dict[str, object], ...]) -> None:
        self._save_payloads("trace_records", values)

    def _save_payloads(self, table: str, values: Iterable[object]) -> None:
        rows = []
        for value in values:
            if isinstance(value, Mapping):
                record_id = value.get("id")
            else:
                record_id = getattr(value, "id", None)
            if record_id is None:
                raise ContractViolation(f"{table} payload must contain an id")
            rows.append((str(record_id), canonical_json(value)))
        self._connection.executemany(
            f"INSERT OR REPLACE INTO {table}(id, payload) VALUES (?, ?)", rows
        )

    def _load_payloads(self, table: str) -> tuple[dict[str, object], ...]:
        rows = self._connection.execute(
            f"SELECT payload FROM {table} ORDER BY id"
        ).fetchall()
        return tuple(json.loads(row[0]) for row in rows)

    def _load_payload(self, table: str, record_id: str) -> dict[str, object] | None:
        row = self._connection.execute(
            f"SELECT payload FROM {table} WHERE id = ?", (str(record_id),)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def save_domain_pack(self, value: Mapping[str, object]) -> dict[str, object]:
        """Persist an immutable domain-pack revision.

        The table key combines ``id`` and ``version``.  A revision can be
        written repeatedly with identical content, but changing any mapping,
        field, unit, constraint, adapter, or ID prefix under the same revision
        raises a contract error; callers must publish a new pack version.
        """

        if not isinstance(value, Mapping) or "id" not in value or "version" not in value:
            raise ContractViolation("domain pack must contain id and version")
        # Validation lives in the application boundary; the repository stores
        # the already validated declaration and only enforces immutable
        # revision identity here.  Keeping this adapter independent of the
        # application layer preserves the import contract.
        pack = dict(value)
        pack_id = str(pack["id"])
        version = int(pack["version"])
        content_hash = canonical_hash(pack)
        payload = dict(pack)
        payload["content_hash"] = content_hash
        key = f"{pack_id}@{version}"
        previous = self._connection.execute(
            "SELECT payload FROM domain_packs WHERE id = ?", (key,)
        ).fetchone()
        if previous is not None:
            existing = json.loads(previous[0])
            if existing.get("content_hash") != content_hash:
                raise ContractViolation(
                    f"domain pack {pack_id} version {version} is immutable; publish a new version"
                )
        self._connection.execute(
            "INSERT OR REPLACE INTO domain_packs(id, payload) VALUES (?, ?)",
            (key, canonical_json(payload)),
        )
        return payload

    def domain_packs(self) -> tuple[dict[str, object], ...]:
        return self._load_payloads("domain_packs")

    def save_scheme_records(self, values: tuple[object, ...]) -> None:
        self._save_payloads("scheme_records", values)

    def scheme_records(self) -> tuple[dict[str, object], ...]:
        return self._load_payloads("scheme_records")

    def load_scheme_record(self, record_id: str) -> dict[str, object] | None:
        return self._load_payload("scheme_records", record_id)

    def save_indicator_envelopes(self, values: tuple[object, ...]) -> None:
        self._save_payloads("indicator_envelopes", values)

    def indicator_envelopes(self) -> tuple[dict[str, object], ...]:
        return self._load_payloads("indicator_envelopes")

    def save_layout_candidates(self, values: tuple[object, ...]) -> None:
        self._save_payloads("layout_candidates", values)

    def layout_candidates(self) -> tuple[dict[str, object], ...]:
        return self._load_payloads("layout_candidates")

    def save_discipline_evaluations(self, values: tuple[object, ...]) -> None:
        self._save_payloads("discipline_evaluations", values)

    def discipline_evaluations(self) -> tuple[dict[str, object], ...]:
        return self._load_payloads("discipline_evaluations")

    def load_discipline_evaluation(self, cache_key: str) -> dict[str, object] | None:
        """Find a cached evaluation by its deterministic cache-key metadata."""

        for payload in self._load_payloads("discipline_evaluations"):
            if payload.get("cache_key") == cache_key:
                return payload
        return None

    def save_optimization_runs(self, values: tuple[object, ...]) -> None:
        self._save_payloads("optimization_runs", values)

    def optimization_runs(self) -> tuple[dict[str, object], ...]:
        return self._load_payloads("optimization_runs")

    def save_workbench(self, value: dict[str, object]) -> None:
        self._connection.execute(
            "INSERT OR REPLACE INTO workbench(id, payload) VALUES ('current', ?)",
            (canonical_json(value),),
        )

    def load_workbench(self) -> dict[str, object] | None:
        row = self._connection.execute(
            "SELECT payload FROM workbench WHERE id = 'current'"
        ).fetchone()
        return json.loads(row[0]) if row else None

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

    def record_audit(self, kind: str, payload: dict[str, object]) -> int:
        cursor = self._connection.execute(
            "INSERT INTO audit_events(kind, payload) VALUES (?, ?)",
            (kind, canonical_json(payload)),
        )
        return int(cursor.lastrowid)

    def save_requirement_records(
        self,
        values: tuple[dict[str, object], ...],
        sequence: int,
        event: str,
    ) -> None:
        """Persist the latest version of each submitted requirement.

        The workbench intentionally keeps only the current editing state. This
        table is the durable project ledger, so replacing the current input
        does not make earlier requirements disappear from the project view.
        """
        updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for value in values:
            record = dict(value)
            record_id = str(record["id"])
            previous_row = self._connection.execute(
                "SELECT first_sequence, payload FROM requirement_records WHERE id = ?",
                (record_id,),
            ).fetchone()
            first_sequence = sequence if previous_row is None else int(previous_row[0])
            previous = json.loads(previous_row[1]) if previous_row is not None else {}
            history = list(previous.get("history", ()))
            history.append(
                {
                    "sequence": sequence,
                    "event": event,
                    "status": record.get("status", "candidate"),
                    "object": record.get("object", ""),
                }
            )
            record["first_seen_sequence"] = first_sequence
            record["last_seen_sequence"] = sequence
            record["updated_at"] = updated_at
            record["history"] = history[-20:]
            self._connection.execute(
                """
                INSERT OR REPLACE INTO requirement_records(
                    id, status, first_sequence, last_sequence, updated_at, payload
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    str(record.get("status", "candidate")),
                    first_sequence,
                    sequence,
                    updated_at,
                    canonical_json(record),
                ),
            )

    def requirement_records(self) -> tuple[dict[str, object], ...]:
        rows = self._connection.execute(
            """
            SELECT status, first_sequence, last_sequence, updated_at, payload
            FROM requirement_records
            ORDER BY last_sequence DESC, id
            """
        ).fetchall()
        records = []
        for status, first_sequence, last_sequence, updated_at, payload in rows:
            record = json.loads(payload)
            record.setdefault("status", status)
            record.setdefault("first_seen_sequence", first_sequence)
            record.setdefault("last_seen_sequence", last_sequence)
            record.setdefault("updated_at", updated_at)
            records.append(record)
        return tuple(records)

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
