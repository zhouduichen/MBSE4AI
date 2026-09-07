"""SQLite implementation of the typed ModelRepository and RunRepository."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Mapping

from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.entities import Entity, EntityKind, EntityMeta, EntityStatus, Producer
from rflp_lite.domain.errors import ConcurrentModificationError, ContractViolation
from rflp_lite.domain.model import ModelGraph, Patch, Revision, apply_patch
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.repository.migrations import apply_v2_schema
from rflp_lite.repository.port import Run, RunRepository, Step


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


class SQLiteModelRepository(RunRepository):
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
            meta = replace(entity.meta, created_revision=entity.meta.created_revision or revision, updated_revision=revision)
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

    def append_patch(self, project_id: str, patch: Patch, expected_revision: int) -> Revision:
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
                patch.reason, graph.snapshot_hash, None,
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
                "INSERT INTO revisions(id, project_id, sequence, parent_id, reason, snapshot_json, snapshot_hash, run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"revision-{graph.revision}", project_id, graph.revision, revision.parent_id, revision.reason, _json(snapshot), revision.snapshot_hash, revision.run_id),
            )
            self._connection.execute(
                "INSERT INTO patches(id, run_id, task_id, operations_json, reason, status) VALUES (?, ?, ?, ?, ?, ?)",
                (patch.id, None, patch.task_id, _json([_operation_dict(item) for item in patch.operations]), patch.reason, "applied"),
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

    def create_run(self, run: Run) -> None:
        self.ensure_project(run.project_id)
        with self._transaction():
            self._connection.execute(
                "INSERT INTO runs(id, project_id, phase, status, attempt, methodology_version, model_profile, input_hash, diagnostics) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run.id, run.project_id, run.phase, run.status, run.attempt, run.methodology_version, run.model_profile, run.input_hash, _json(run.diagnostics)),
            )
            for step in run.steps:
                self._connection.execute(
                    "INSERT OR REPLACE INTO steps(run_id, task_id, status, attempt, input_hash, output_patch_id, diagnostics) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (step.run_id, step.task_id, step.status, step.attempt, step.input_hash, step.output_patch_id, _json(step.diagnostics)),
                )

    def update_step(self, step: Step) -> None:
        with self._transaction():
            self._connection.execute(
                "INSERT OR REPLACE INTO steps(run_id, task_id, status, attempt, input_hash, output_patch_id, diagnostics) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (step.run_id, step.task_id, step.status, step.attempt, step.input_hash, step.output_patch_id, _json(step.diagnostics)),
            )

    def update_run(self, run_id: str, status: str, diagnostics: tuple[str, ...] = ()) -> None:
        with self._transaction():
            self._connection.execute(
                "UPDATE runs SET status = ?, diagnostics = ? WHERE id = ?",
                (status, _json(diagnostics), run_id),
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
                Step(item["run_id"], item["task_id"], item["status"], item["attempt"], item["input_hash"], item["output_patch_id"], tuple(json.loads(item["diagnostics"])))
                for item in steps
            ),
        )
