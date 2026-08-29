"""Atomic Workbench mutation coordinator."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict

from rflp_lite.application.workbench.mutation import (
    MutationResult,
    WorkbenchMutation,
)
from rflp_lite.application.workbench.queries import load_snapshot
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.ports.repositories import WorkbenchRepositoryPort


class WorkbenchCommitCoordinator:
    """The single new entry point for atomic Workbench mutations."""

    def __init__(self, repository: WorkbenchRepositoryPort, workspace: str) -> None:
        self.repository = repository
        self.workspace = workspace

    def snapshot(self):
        return load_snapshot(self.repository, self.workspace)

    def commit(
        self,
        mutation: WorkbenchMutation,
        *,
        expected_revision: int | None,
        expected_content_revision: int | None = None,
        event: str = "workbench.mutated",
        audit_payload: dict[str, object] | None = None,
        deleted_requirement_ids: tuple[str, ...] = (),
    ) -> MutationResult:
        with self.repository.transaction():
            current = self.repository.load_workbench() or {}
            working = deepcopy(current)
            result = mutation(working)
            if not isinstance(result, MutationResult):
                raise ContractViolation("Workbench mutation must return MutationResult")
            if not isinstance(result.state, dict):
                raise ContractViolation("Workbench mutation state must be an object")
            saved = self.repository.save_workbench(
                result.state,
                event,
                expected_revision=expected_revision,
                expected_content_revision=expected_content_revision,
            )
            event_payload: dict[str, object] = {
                "workspace": self.workspace,
                "revision": saved.get("revision", 0),
                "content_revision": saved.get("content_revision", 0),
                "changed_ids": result.changed_ids,
                "invalidated_sections": result.invalidated_sections,
                "mutation_kind": result.mutation_kind.value,
            }
            if audit_payload:
                event_payload.update(audit_payload)
            if result.diagnostics:
                event_payload["diagnostics"] = tuple(
                    asdict(item) for item in result.diagnostics
                )
            sequence = self.repository.record_audit(event, event_payload)
            self.repository.save_requirement_records(
                self._requirement_records(saved), sequence, event
            )
            if deleted_requirement_ids:
                self.repository.mark_requirement_deleted(
                    deleted_requirement_ids, sequence, event
                )
            self.repository.save_trace_records(
                tuple(item for item in saved.get("trace_links", ()) if isinstance(item, dict))
            )
            return MutationResult(
                state=saved,
                changed_ids=result.changed_ids,
                invalidated_sections=result.invalidated_sections,
                diagnostics=result.diagnostics,
                mutation_kind=result.mutation_kind,
            )

    @staticmethod
    def _requirement_records(
        state: dict[str, object]
    ) -> tuple[dict[str, object], ...]:
        records: list[dict[str, object]] = []
        for item in state.get("claims", ()):
            if not isinstance(item, dict) or not item.get("id"):
                continue
            records.append(
                {
                    "id": str(item["id"]),
                    "subject": item.get("subject", ""),
                    "predicate": item.get("predicate", ""),
                    "object": item.get("object", ""),
                    "status": item.get("status", "candidate"),
                    "source_type": item.get("source_type", "provisional"),
                    "confidence": item.get("confidence", 0.0),
                }
            )
        return tuple(records)
