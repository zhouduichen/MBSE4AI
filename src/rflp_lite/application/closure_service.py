"""Durable closure and export manifest service."""

from __future__ import annotations

from dataclasses import dataclass

from rflp_lite.domain.errors import ContractViolation
from rflp_lite.methodology.closure import evaluate_strict_closure
from rflp_lite.methodology.gates import global_gate


@dataclass(frozen=True, slots=True)
class ClosureResult:
    project_id: str
    run_id: str
    revision: int
    manifest: dict[str, object]
    gate_snapshot: tuple[dict[str, object], ...]
    audit_summary: dict[str, object]
    status: str = "completed"
    issues: tuple[dict[str, object], ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id, "run_id": self.run_id, "revision": self.revision,
            "manifest": self.manifest, "gate_snapshot": list(self.gate_snapshot),
            "audit_summary": self.audit_summary, "status": self.status,
            "issues": list(self.issues),
        }


class ClosureService:
    def __init__(self, repository):
        self.repository = repository

    def close(
        self,
        project_id: str,
        run_id: str,
        *,
        gate_snapshot: tuple[dict[str, object], ...] = (),
    ) -> ClosureResult:
        graph = self.repository.load_graph(project_id)
        issue_reader = getattr(self.repository, "list_issues", None)
        issue_records = issue_reader(project_id) if callable(issue_reader) else ()
        assessment = evaluate_strict_closure(graph, issue_records=issue_records)
        if not assessment.passed:
            result = ClosureResult(
                project_id,
                run_id,
                graph.revision,
                {},
                gate_snapshot,
                self._audit(project_id, run_id),
                "blocked",
                tuple(issue.as_dict() for issue in assessment.issues),
            )
            self._record_block(project_id, run_id, result)
            return result
        final_gate = global_gate(graph)
        if not final_gate.passed:
            result = ClosureResult(
                project_id,
                run_id,
                graph.revision,
                {},
                gate_snapshot,
                self._audit(project_id, run_id),
                "blocked",
                tuple({
                    "code": issue.code,
                    "message": f"Global-Gate blocked Closure: {issue.code}",
                    "entity_ids": list(issue.entity_ids),
                    "details": {},
                } for issue in final_gate.issues),
            )
            self._record_block(project_id, run_id, result)
            return result
        manifest = {
            "format": "ai4mbse.model-manifest.v1",
            "project_id": project_id,
            "revision": graph.revision,
            "entities": [item.as_dict() for item in graph.entities],
            "relations": [
                {"id": item.id, "source_id": item.source_id, "predicate": item.predicate.value,
                 "target_id": item.target_id, "evidence_ids": list(item.evidence_ids)}
                for item in graph.relations
            ],
            "exports": ["model.json", "audit.json", "gate-snapshot.json"],
        }
        audit_reader = getattr(self.repository, "audit_summary", None)
        audit = audit_reader(project_id, run_id) if callable(audit_reader) else {"run_id": run_id}
        result = ClosureResult(project_id, run_id, graph.revision, manifest, gate_snapshot, audit)
        saver = getattr(self.repository, "save_closure", None)
        if callable(saver):
            saver(project_id, run_id, result.as_dict())
        freezer = getattr(self.repository, "freeze_revision", None)
        if callable(freezer):
            freezer(project_id, graph.revision)
        return result

    def _audit(self, project_id: str, run_id: str) -> dict[str, object]:
        reader = getattr(self.repository, "audit_summary", None)
        return reader(project_id, run_id) if callable(reader) else {"run_id": run_id}

    def _record_block(self, project_id: str, run_id: str, result: ClosureResult) -> None:
        recorder = getattr(self.repository, "record_audit", None)
        if callable(recorder):
            recorder(project_id, "closure.blocked", {
                "run_id": run_id,
                "revision": result.revision,
                "issues": list(result.issues),
            })
