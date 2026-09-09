"""Guarded engineering review commands for ModelGraph entities."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping
from uuid import uuid4

from rflp_lite.domain.entities import EntityStatus, Producer
from rflp_lite.domain.errors import ConflictError, ContractViolation, NotFoundError
from rflp_lite.domain.model import Patch, UpdateEntity


@dataclass(frozen=True, slots=True)
class ReviewCommandResult:
    project_id: str
    entity_id: str
    action: str
    previous_status: str
    status: str
    revision: Mapping[str, object]
    patch_id: str
    audit_kind: str

    def as_dict(self) -> Mapping[str, object]:
        return asdict(self)


class ReviewService:
    def __init__(self, model_service):
        self.model_service = model_service
        self.repository = model_service.repository

    def _entity(self, project_id: str, entity_id: str):
        entity = self.model_service.graph(project_id).entity_index.get(entity_id)
        if entity is None:
            raise NotFoundError(f"entity not found: {entity_id}")
        return entity

    def _apply(self, project_id: str, entity_id: str, action: str, fields: Mapping[str, object], expected_revision: int | None, reason: str):
        graph = self.model_service.graph(project_id)
        entity = graph.entity_index.get(entity_id)
        if entity is None:
            raise NotFoundError(f"entity not found: {entity_id}")
        if expected_revision is None:
            expected_revision = graph.revision
        task_id = f"review.{action}"
        patch = Patch.create(project_id, task_id, (UpdateEntity(entity_id, fields),), reason, int(expected_revision))
        revision = self.model_service.apply_patch(project_id, patch, int(expected_revision))
        self.repository.record_audit(project_id, f"review.{action}", {"entity_id": entity_id, "patch_id": patch.id, "revision": revision.sequence, "previous_status": entity.meta.status.value, "status": fields.get("status", entity.meta.status.value), "producer": fields.get("producer", entity.meta.producer.value), "reason": reason})
        return ReviewCommandResult(project_id, entity_id, action, entity.meta.status.value, str(fields.get("status", entity.meta.status.value)), asdict(revision), patch.id, f"review.{action}")

    def accept_entity(self, project_id: str, entity_id: str, *, expected_revision: int | None = None) -> ReviewCommandResult:
        entity = self._entity(project_id, entity_id)
        if entity.meta.status not in {EntityStatus.CANDIDATE, EntityStatus.VALIDATED}:
            raise ContractViolation(f"cannot accept entity from status {entity.meta.status.value}")
        return self._apply(project_id, entity_id, "accept", {"status": EntityStatus.ACCEPTED.value, "producer": Producer.USER.value}, expected_revision, "user accepted engineering entity")

    def reject_entity(self, project_id: str, entity_id: str, *, expected_revision: int | None = None) -> ReviewCommandResult:
        entity = self._entity(project_id, entity_id)
        if entity.meta.status is EntityStatus.LOCKED:
            raise ConflictError(f"locked entity cannot be rejected: {entity_id}")
        if entity.meta.status not in {EntityStatus.CANDIDATE, EntityStatus.VALIDATED, EntityStatus.ACCEPTED}:
            raise ContractViolation(f"cannot reject entity from status {entity.meta.status.value}")
        return self._apply(project_id, entity_id, "reject", {"status": EntityStatus.REJECTED.value, "producer": Producer.USER.value}, expected_revision, "user rejected engineering entity")

    def lock_entity(self, project_id: str, entity_id: str, *, expected_revision: int | None = None) -> ReviewCommandResult:
        entity = self._entity(project_id, entity_id)
        if entity.meta.status is not EntityStatus.ACCEPTED:
            raise ContractViolation(f"only accepted entities can be locked: {entity_id}")
        return self._apply(project_id, entity_id, "lock", {"status": EntityStatus.LOCKED.value, "producer": Producer.USER.value}, expected_revision, "user locked accepted engineering entity")

    def unlock_entity(self, project_id: str, entity_id: str, *, expected_revision: int | None = None) -> ReviewCommandResult:
        entity = self._entity(project_id, entity_id)
        if entity.meta.status is not EntityStatus.LOCKED:
            raise ContractViolation(f"only locked entities can be unlocked: {entity_id}")
        return self._apply(project_id, entity_id, "unlock", {"status": EntityStatus.ACCEPTED.value, "producer": Producer.USER.value, "payload": {"user_modified": False}}, expected_revision, "user unlocked engineering entity")

    def edit_entity(self, project_id: str, entity_id: str, *, statement: str | None = None, name: str | None = None, payload: Mapping[str, object] | None = None, expected_revision: int | None = None) -> ReviewCommandResult:
        entity = self._entity(project_id, entity_id)
        if entity.meta.status is EntityStatus.LOCKED:
            raise ConflictError(f"locked entity cannot be edited: {entity_id}")
        next_payload = dict(payload or {})
        if statement is not None:
            next_payload["statement"] = str(statement).strip()
        if not next_payload and name is None:
            raise ContractViolation("edit requires statement, name, or payload")
        fields: Mapping[str, object] = {"producer": Producer.USER.value, "payload": {**next_payload, "user_modified": True}}
        if name is not None:
            fields["name"] = str(name).strip()
        if entity.meta.status is not EntityStatus.CANDIDATE:
            fields["status"] = EntityStatus.CANDIDATE.value
        return self._apply(project_id, entity_id, "edit", fields, expected_revision, "user edited engineering entity; downstream trace marked stale")

    def request_reanalysis(self, project_id: str, entity_id: str, *, expected_revision: int | None = None) -> Mapping[str, object]:
        entity = self._entity(project_id, entity_id)
        graph = self.model_service.graph(project_id)
        if expected_revision is not None and int(expected_revision) != graph.revision:
            raise ConflictError(f"stale re-analysis request: expected {expected_revision}, current {graph.revision}")
        task_sets = {
            "requirement": ("system_requirement_derivation", "function_identification", "logical_analysis", "physical_candidates", "verification_validation"),
            "function": ("functional_decomposition", "functional_interaction", "logical_analysis", "physical_candidates", "verification_validation"),
        }
        selected = task_sets.get(entity.kind.value, ("global_cross_analysis", "verification_validation"))
        request_id = f"reanalysis-{uuid4().hex[:16]}"
        payload = {"request_id": request_id, "entity_id": entity_id, "trigger_revision": graph.revision, "selected_tasks": list(selected), "reason": "local impact routing from review action", "status": "queued"}
        self.repository.record_audit(project_id, "review.reanalysis.requested", payload)
        return payload
