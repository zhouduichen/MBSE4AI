"""SQLite implementation of the typed ModelRepository and RunRepository."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Mapping, Sequence

from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.entities import Entity, EntityKind, EntityMeta, EntityStatus, Producer
from rflp_lite.domain.errors import ConcurrentModificationError, ContractViolation
from rflp_lite.domain.model import ModelGraph, Patch, Revision, apply_patch
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.repository.migrations import apply_v2_schema
from rflp_lite.repository.port import ModelRepository, Run, RunRepository, Step


def _json(value: object) -> str:
    return canonical_json(value)


def _operation_dict(operation: object) -> dict[str, object]:
    if hasattr(operation, "entity"):
        entity = operation.entity
        return {"op": "ADD", "entity": entity.as_dict()}
    if hasattr(operation, "field_patch"):
        return {"op": "UPDATE", "entity_id": operation.entity_id, "field_patch": dict(operation.field_patch)}
    if hasattr(operation, "predicate"):
        return {"op": "RELATE", "source_id": operation.source_id, "predicate": operation.predicate.value, "target_id": operation.target_id, "evidence_ids": list(operation.evidence_ids)}
    return {"op": "DEPRECATE", "entity_id": operation.entity_id}


def _entity_from_dict(raw: Mapping[str, object]) -> Entity:
    meta = EntityMeta(
        id=str(raw["id"]),
        kind=EntityKind(str(raw["kind"])),
        name=str(raw["name"]),
        status=EntityStatus(str(raw.get("status", "candidate"))),
        producer=Producer(str(raw.get("producer", "rule"))),
        confidence=float(raw["confidence"]) if raw.get("confidence") is not None else None,
        source_ids=tuple(str(value) for value in raw.get("source_ids", ())),
        evidence_ids=tuple(str(value) for value in raw.get("evidence_ids", ())),
        lifecycle_ids=tuple(str(value) for value in raw.get("lifecycle_ids", ())),
        created_revision=int(raw.get("created_revision", 0)),
        updated_revision=int(raw.get("updated_revision", 0)),
    )
    payload = raw.get("payload", {})
    if not isinstance(payload, Mapping):
        raise ContractViolation("entity payload must be an object")
    return Entity(meta, dict(payload))


class SQLiteModelRepository(ModelRepository, RunRepository):
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        apply_v2_schema(self._connection)

    def close(self) -> None:
        self._connection.close()

    @contextmanager
    def _transaction(self):
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def ensure_project(self, project_id: str, name: str = "") -> None:
        project_id = str(project_id).strip()
        if not project_id:
            raise ContractViolation("project id is required")
        with self._transaction():
            self._connection.execute(
                "INSERT OR IGNORE INTO projects(id, name) VALUES (?, ?)",
                (project_id, name.strip() or project_id),
            )

    def _current_revision(self, project_id: str) -> int:
        row = self._connection.execute(
            "SELECT revision FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if row is None:
            raise ContractViolation(f"project not found: {project_id}")
        return int(row[0])

    def load_graph(self, project_id: str) -> ModelGraph:
        with self._lock:
            revision = self._current_revision(project_id)
            rows = self._connection.execute(
                "SELECT * FROM entities WHERE project_id = ? ORDER BY id", (project_id,)
            ).fetchall()
            entities = tuple(
                _entity_from_dict({
                    "id": row["id"], "kind": row["kind"], "name": row["name"],
                    "status": row["status"], "producer": row["producer"],
                    "confidence": row["confidence"], "source_ids": json.loads(row["source_ids"]),
                    "evidence_ids": json.loads(row["evidence_ids"]),
                    "lifecycle_ids": json.loads(row["lifecycle_hint"]),
                    "created_revision": row["created_revision"], "updated_revision": row["updated_revision"],
                    "payload": json.loads(row["payload_json"]),
                }) for row in rows
            )
            relation_rows = self._connection.execute(
                "SELECT * FROM relations WHERE project_id = ? ORDER BY id", (project_id,)
            ).fetchall()
            from rflp_lite.domain.model import Relation

            relations = tuple(
                Relation(row["id"], row["source_id"], RelationPredicate(row["predicate"]), row["target_id"], tuple(json.loads(row["evidence_ids"])))
                for row in relation_rows
            )
        return ModelGraph(project_id, entities, relations, revision)

    def list_entities(self, project_id: str, kind: EntityKind | None = None) -> tuple[Entity, ...]:
        graph = self.load_graph(project_id)
        return tuple(item for item in graph.entities if kind is None or item.kind is kind)

    def _persist_graph(self, graph: ModelGraph, revision: int) -> None:
        for entity in graph.entities:
            meta = replace(
                entity.meta,
                created_revision=entity.meta.created_revision or revision,
                updated_revision=entity.meta.updated_revision or revision,
            )
            self._connection.execute(
                "INSERT OR REPLACE INTO entities(id, project_id, kind, name, status, lifecycle_hint, producer, confidence, payload_json, source_ids, evidence_ids, created_revision, updated_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (meta.id, graph.project_id, meta.kind.value, meta.name, meta.status.value, _json(meta.lifecycle_ids), meta.producer.value, meta.confidence, _json(entity.payload), _json(meta.source_ids), _json(meta.evidence_ids), meta.created_revision, meta.updated_revision),
            )
        self._connection.execute("DELETE FROM relations WHERE project_id = ?", (graph.project_id,))
        for relation in graph.relations:
            self._connection.execute(
                "INSERT INTO relations(id, project_id, source_id, predicate, target_id, evidence_ids, created_revision) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (relation.id, graph.project_id, relation.source_id, relation.predicate.value, relation.target_id, _json(relation.evidence_ids), revision),
            )
        self._connection.execute("DELETE FROM entities_fts WHERE project_id = ?", (graph.project_id,))
        for entity in graph.entities:
            self._connection.execute(
                "INSERT INTO entities_fts(project_id, entity_id, name, payload) VALUES (?, ?, ?, ?)",
                (graph.project_id, entity.id, entity.meta.name, _json(entity.payload)),
            )

    def append_patch(
        self, project_id: str, patch: Patch, expected_revision: int, *, run_id: str | None = None
    ) -> Revision:
        if patch.project_id != project_id or patch.expected_revision != expected_revision:
            raise ContractViolation("patch project or expected revision does not match request")
        with self._transaction():
            current = self._current_revision(project_id)
            if current != expected_revision:
                raise ConcurrentModificationError(
                    f"stale ModelGraph revision: expected {expected_revision}, current {current}"
                )
            graph = apply_patch(self.load_graph(project_id), patch)
            revision = Revision(
                project_id, graph.revision, f"revision-{current}" if current else None,
                patch.reason, graph.snapshot_hash, run_id,
            )
            self._persist_graph(graph, graph.revision)
            snapshot = {"entities": [item.as_dict() for item in graph.entities], "relations": [
                {"id": item.id, "source_id": item.source_id, "predicate": item.predicate.value, "target_id": item.target_id, "evidence_ids": list(item.evidence_ids)}
                for item in graph.relations
            ]}
            self._connection.execute(
                "UPDATE projects SET revision = ?, content_revision = ? WHERE id = ?",
                (graph.revision, graph.revision, project_id),
            )
            self._connection.execute(
                "INSERT INTO revisions(id, project_id, sequence, parent_id, reason, snapshot_json, snapshot_hash, run_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f"revision-{graph.revision}", project_id, graph.revision, revision.parent_id, revision.reason, _json(snapshot), revision.snapshot_hash, revision.run_id, time.time()),
            )
            self._connection.execute(
                "INSERT INTO patches(id, run_id, task_id, operations_json, reason, status, input_hash, output_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (patch.id, run_id, patch.task_id, _json([_operation_dict(item) for item in patch.operations]), patch.reason, "applied", canonical_hash((project_id, expected_revision, patch.id)), graph.snapshot_hash),
            )
            self._connection.execute(
                "INSERT INTO audit_events(project_id, kind, payload) VALUES (?, ?, ?)",
                (project_id, "model.patch.applied", _json({"patch_id": patch.id, "revision": graph.revision})),
            )
            return revision

    def list_issues(self, project_id: str) -> tuple[dict[str, object], ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM issues WHERE project_id = ? ORDER BY id", (project_id,)
            ).fetchall()
        return tuple({
            "id": row["id"], "code": row["code"], "severity": row["severity"],
            "entity_ids": json.loads(row["entity_ids"]), "status": row["status"],
        } for row in rows)

    def save_issue(self, project_id: str, issue: Mapping[str, object]) -> None:
        self.ensure_project(project_id)
        issue_id = str(issue.get("id", "")).strip()
        if not issue_id:
            raise ContractViolation("issue id is required")
        with self._transaction():
            self._connection.execute(
                "INSERT OR REPLACE INTO issues(id, project_id, run_id, task_id, code, severity, entity_ids, suggested_rollback, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    issue_id,
                    project_id,
                    issue.get("run_id"),
                    issue.get("task_id"),
                    str(issue.get("code", "issue")),
                    str(issue.get("severity", "warning")),
                    _json(issue.get("entity_ids", [])),
                    issue.get("suggested_rollback"),
                    str(issue.get("status", "open")),
                ),
            )

    def save_document(self, project_id: str, document: Mapping[str, object]) -> None:
        self.ensure_project(project_id)
        document_id = str(document.get("id", "")).strip()
        if not document_id:
            raise ContractViolation("document id is required")
        with self._transaction():
            self._connection.execute(
                "INSERT OR REPLACE INTO documents(id, project_id, kind, path, name, sha256, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    document_id,
                    project_id,
                    str(document.get("kind", "document")),
                    str(document.get("path", "")),
                    str(document.get("name", document.get("path", ""))),
                    str(document.get("sha256", "")),
                    _json(document.get("metadata", {})),
                ),
            )

    def save_source_regions(
        self, project_id: str, regions: Sequence[Mapping[str, object]]
    ) -> None:
        self.ensure_project(project_id)
        with self._transaction():
            for region in regions:
                region_id = str(region.get("id", "")).strip()
                document_id = str(region.get("document_id", region.get("artifact_id", ""))).strip()
                if not region_id or not document_id:
                    raise ContractViolation("source region id and document id are required")
                self._connection.execute(
                    "INSERT OR REPLACE INTO source_regions(id, document_id, page, locator, text, bbox, heading_path) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        region_id,
                        document_id,
                        region.get("page"),
                        str(region.get("locator", "")),
                        str(region.get("text", "")),
                        _json(region.get("bbox", [])),
                        _json(region.get("heading_path", [])),
                    ),
                )
                self._connection.execute("DELETE FROM source_regions_fts WHERE region_id = ?", (region_id,))
                self._connection.execute(
                    "INSERT INTO source_regions_fts(project_id, region_id, text, locator, heading_path) VALUES (?, ?, ?, ?, ?)",
                    (project_id, region_id, str(region.get("text", "")), str(region.get("locator", "")), _json(region.get("heading_path", []))),
                )

    def has_documents(self, project_id: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM documents WHERE project_id = ? LIMIT 1", (project_id,)
            ).fetchone()
        return row is not None

    def save_evidence(self, project_id: str, evidence: Mapping[str, object]) -> None:
        self.ensure_project(project_id)
        evidence_id = str(evidence.get("id", "")).strip()
        if not evidence_id:
            raise ContractViolation("evidence id is required")
        with self._transaction():
            self._connection.execute(
                "INSERT OR REPLACE INTO evidence(id, project_id, source_type, source_id, locator, claim, excerpt, authority, relevance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    evidence_id,
                    project_id,
                    str(evidence.get("source_type", "user_document")),
                    str(evidence.get("source_id", "")),
                    str(evidence.get("locator", "")),
                    str(evidence.get("claim", "")),
                    str(evidence.get("excerpt", "")),
                    float(evidence["authority"]) if evidence.get("authority") is not None else None,
                    float(evidence["relevance"]) if evidence.get("relevance") is not None else None,
                ),
            )
            self._connection.execute("DELETE FROM evidence_fts WHERE evidence_id = ?", (evidence_id,))
            self._connection.execute(
                "INSERT INTO evidence_fts(project_id, evidence_id, claim, excerpt) VALUES (?, ?, ?, ?)",
                (project_id, evidence_id, str(evidence.get("claim", "")), str(evidence.get("excerpt", ""))),
            )

    def list_evidence(self, project_id: str) -> tuple[dict[str, object], ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM evidence WHERE project_id = ? ORDER BY id", (project_id,)
            ).fetchall()
        return tuple(
            {
                "id": row["id"], "source_type": row["source_type"], "source_id": row["source_id"],
                "locator": row["locator"], "claim": row["claim"], "excerpt": row["excerpt"],
                "authority": row["authority"], "relevance": row["relevance"],
            }
            for row in rows
        )

    def audit_summary(self, project_id: str, run_id: str) -> dict[str, object]:
        with self._lock:
            events = self._connection.execute(
                "SELECT sequence, kind, payload FROM audit_events WHERE project_id = ? ORDER BY sequence",
                (project_id,),
            ).fetchall()
            patches = self._connection.execute(
                "SELECT id, task_id, operations_json, reason, status, input_hash, output_hash, provider_id, model_id FROM patches WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
            revisions = self._connection.execute(
                "SELECT id, sequence, parent_id, reason, snapshot_hash, run_id FROM revisions WHERE project_id = ? AND run_id = ? ORDER BY sequence",
                (project_id, run_id),
            ).fetchall()
        return {
            "run_id": run_id,
            "events": [{"sequence": row["sequence"], "kind": row["kind"], "payload": json.loads(row["payload"])} for row in events],
            "patches": [dict(row) for row in patches],
            "revisions": [dict(row) for row in revisions],
        }

    def record_audit(self, project_id: str, kind: str, payload: Mapping[str, object]) -> None:
        self.ensure_project(project_id)
        with self._transaction():
            self._connection.execute(
                "INSERT INTO audit_events(project_id, kind, payload) VALUES (?, ?, ?)",
                (project_id, kind, _json(payload)),
            )

    def list_revisions(self, project_id: str) -> tuple[Mapping[str, object], ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT id, project_id, sequence, parent_id, reason, snapshot_hash, run_id, created_at FROM revisions WHERE project_id = ? ORDER BY sequence",
                (project_id,),
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def load_revision(self, project_id: str, sequence: int) -> Mapping[str, object] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT id, project_id, sequence, parent_id, reason, snapshot_json, snapshot_hash, run_id FROM revisions WHERE project_id = ? AND sequence = ?",
                (project_id, int(sequence)),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["snapshot"] = json.loads(result.pop("snapshot_json"))
        return result

    def list_patches(self, project_id: str) -> tuple[Mapping[str, object], ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT p.id, p.run_id, p.task_id, p.operations_json, p.reason, p.status, p.input_hash, p.output_hash, p.provider_id, p.model_id, r.sequence AS revision FROM patches p LEFT JOIN revisions r ON r.project_id = ? AND r.snapshot_hash = p.output_hash WHERE r.project_id = ? ORDER BY r.sequence, p.id",
                (project_id, project_id),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["operations"] = json.loads(item.pop("operations_json"))
            result.append(item)
        return tuple(result)

    def list_runs(self, project_id: str) -> tuple[Run, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT id FROM runs WHERE project_id = ? ORDER BY started_at, id", (project_id,)
            ).fetchall()
        return tuple(run for row in rows if (run := self.load_run(project_id, str(row["id"]))) is not None)

    def list_audit_events(self, project_id: str) -> tuple[Mapping[str, object], ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT sequence, project_id, kind, payload FROM audit_events WHERE project_id = ? ORDER BY sequence",
                (project_id,),
            ).fetchall()
        return tuple({**dict(row), "payload": json.loads(row["payload"])} for row in rows)

    def update_patch_trace(self, patch_id: str, *, provider_id: str = "", model_id: str = "") -> None:
        with self._transaction():
            self._connection.execute(
                "UPDATE patches SET provider_id = ?, model_id = ? WHERE id = ?",
                (provider_id, model_id, patch_id),
            )

    def save_closure(self, project_id: str, run_id: str, payload: Mapping[str, object]) -> None:
        with self._transaction():
            self._connection.execute(
                "INSERT OR REPLACE INTO closures(project_id, run_id, revision, manifest_json, gate_snapshot_json, audit_summary_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (project_id, run_id, int(payload.get("revision", 0)), _json(payload.get("manifest", {})), _json(payload.get("gate_snapshot", [])), _json(payload.get("audit_summary", {})), time.time()),
            )
            self._connection.execute(
                "INSERT INTO audit_events(project_id, kind, payload) VALUES (?, ?, ?)",
                (project_id, "run.closed", _json({"run_id": run_id, "revision": payload.get("revision", 0)})),
            )

    def freeze_revision(self, project_id: str, revision: int) -> None:
        with self._transaction():
            self._connection.execute(
                "UPDATE projects SET status = 'frozen', content_revision = ? WHERE id = ?",
                (revision, project_id),
            )

    def search_fts(self, project_id: str, query: str, limit: int = 20) -> tuple[dict[str, object], ...]:
        clean_query = " ".join(str(query).split()).strip()
        if not clean_query:
            return ()
        bounded_limit = max(1, min(int(limit), 100))
        with self._lock:
            results: list[dict[str, object]] = []
            for table, columns, kind in (
                ("source_regions_fts", "region_id, text, locator, heading_path", "source_region"),
                ("entities_fts", "entity_id, name, payload", "entity"),
                ("evidence_fts", "evidence_id, claim, excerpt", "evidence"),
            ):
                try:
                    rows = self._connection.execute(
                        f"SELECT {columns} FROM {table} WHERE project_id = ? AND {table} MATCH ? LIMIT ?",
                        (project_id, clean_query, bounded_limit),
                    ).fetchall()
                except sqlite3.OperationalError:
                    search_columns = columns.split(", ")[1:]
                    predicate = " OR ".join("{} LIKE ?".format(column) for column in search_columns)
                    rows = self._connection.execute(
                        f"SELECT {columns} FROM {table} WHERE project_id = ? AND ({predicate}) LIMIT ?",
                        (project_id, *(f"%{clean_query}%" for _ in search_columns), bounded_limit),
                    ).fetchall()
                for row in rows:
                    values = dict(row)
                    values["kind"] = kind
                    results.append(values)
                    if len(results) >= bounded_limit:
                        return tuple(results)
        return tuple(results)

    def create_run(self, run: Run) -> None:
        self.ensure_project(run.project_id)
        with self._transaction():
            self._connection.execute(
                "INSERT INTO runs(id, project_id, phase, status, attempt, methodology_version, model_profile, input_hash, diagnostics, provider_id, model_id, execution_mode, context_hash, task_spec_hash, prompt_hash, output_hash, started_at, completed_at, lease, heartbeat) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run.id, run.project_id, run.phase, run.status, run.attempt, run.methodology_version, run.model_profile, run.input_hash, _json(run.diagnostics), run.provider_id, run.model_id, run.execution_mode, run.context_hash, run.task_spec_hash, run.prompt_hash, run.output_hash, run.started_at, run.completed_at, run.lease, run.heartbeat),
            )
            for step in run.steps:
                self._connection.execute(
                    "INSERT OR REPLACE INTO steps(run_id, task_id, status, attempt, input_hash, output_patch_id, diagnostics, output_hash, provider_id, model_id, prompt_template_id, prompt_version, prompt_hash, context_hash, started_at, completed_at, task_spec_hash, repair_strategy, repair_round) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (step.run_id, step.task_id, step.status, step.attempt, step.input_hash, step.output_patch_id, _json(step.diagnostics), step.output_hash, step.provider_id, step.model_id, step.prompt_template_id, step.prompt_version, step.prompt_hash, step.context_hash, step.started_at, step.completed_at, step.task_spec_hash, step.repair_strategy, step.repair_round),
                )

    def update_step(self, step: Step) -> None:
        with self._transaction():
            self._connection.execute(
                "INSERT OR REPLACE INTO steps(run_id, task_id, status, attempt, input_hash, output_patch_id, diagnostics, output_hash, provider_id, model_id, prompt_template_id, prompt_version, prompt_hash, context_hash, started_at, completed_at, task_spec_hash, repair_strategy, repair_round) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (step.run_id, step.task_id, step.status, step.attempt, step.input_hash, step.output_patch_id, _json(step.diagnostics), step.output_hash, step.provider_id, step.model_id, step.prompt_template_id, step.prompt_version, step.prompt_hash, step.context_hash, step.started_at, step.completed_at, step.task_spec_hash, step.repair_strategy, step.repair_round),
            )

    def update_run(self, run_id: str, status: str, diagnostics: tuple[str, ...] = ()) -> None:
        with self._transaction():
            self._connection.execute(
                "UPDATE runs SET status = ?, diagnostics = ?, completed_at = CASE WHEN ? IN ('completed', 'failed', 'degraded', 'blocked', 'cancelled') THEN ? ELSE completed_at END WHERE id = ?",
                (status, _json(diagnostics), status, time.time(), run_id),
            )

    def load_run(self, project_id: str, run_id: str) -> Run | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM runs WHERE id = ? AND project_id = ?", (run_id, project_id)
            ).fetchone()
            if row is None:
                return None
            steps = self._connection.execute(
                "SELECT * FROM steps WHERE run_id = ? ORDER BY task_id", (run_id,)
            ).fetchall()
        return Run(
            row["id"], row["project_id"], row["phase"], row["status"], row["attempt"],
            row["methodology_version"], row["model_profile"], row["input_hash"],
            tuple(json.loads(row["diagnostics"])), tuple(
                Step(item["run_id"], item["task_id"], item["status"], item["attempt"], item["input_hash"], item["output_patch_id"], tuple(json.loads(item["diagnostics"])), item["output_hash"], item["provider_id"], item["model_id"], item["prompt_template_id"], item["context_hash"], item["started_at"], item["completed_at"], item["prompt_version"], item["prompt_hash"], item["task_spec_hash"], item["repair_strategy"], item["repair_round"])
                for item in steps
            ),
            row["provider_id"], row["model_id"], row["execution_mode"], row["context_hash"],
            row["task_spec_hash"], row["prompt_hash"], row["output_hash"], row["started_at"],
            row["completed_at"], row["lease"], row["heartbeat"],
        )

    def claim_run(self, project_id: str, run_id: str, lease: str, now: float) -> bool:
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE runs SET lease = ?, heartbeat = ? WHERE id = ? AND project_id = ? AND (lease = '' OR heartbeat < ?)",
                (lease, now, run_id, project_id, now - 300),
            )
            return cursor.rowcount == 1

    def heartbeat_run(self, run_id: str, lease: str, now: float) -> None:
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE runs SET heartbeat = ? WHERE id = ? AND lease = ?",
                (now, run_id, lease),
            )
            if cursor.rowcount != 1:
                raise ContractViolation("run lease is not held")

    def interrupt_run(self, run_id: str, lease: str) -> None:
        with self._transaction():
            self._connection.execute(
                "UPDATE runs SET status = 'cancelled', lease = '', completed_at = ? WHERE id = ? AND lease = ?",
                (time.time(), run_id, lease),
            )
