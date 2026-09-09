"""Stable identity, revision, and lock protection checks."""

from __future__ import annotations

from rflp_lite.domain.entities import EntityStatus
from rflp_lite.domain.errors import MethodologyValidationError
from rflp_lite.domain.model import AddEntity, Deprecate, UpdateEntity
from rflp_lite.methodology.validation import ValidationContext


def validate(context: ValidationContext) -> None:
    patch = context.response.patch
    if patch is None:
        return
    if patch.project_id != context.project_id:
        raise MethodologyValidationError("identity_conflict", "patch project does not match validation project")
    if patch.expected_revision != context.graph.revision:
        raise MethodologyValidationError("cas_conflict", "patch expected revision is stale")
    current = context.graph.entity_index
    added: set[str] = set()
    for operation in patch.operations:
        if isinstance(operation, AddEntity):
            if operation.entity.id in current or operation.entity.id in added:
                raise MethodologyValidationError("identity_conflict", f"entity id already exists: {operation.entity.id}")
            added.add(operation.entity.id)
        elif isinstance(operation, (UpdateEntity, Deprecate)):
            entity = current.get(operation.entity_id)
            if entity is None:
                raise MethodologyValidationError("identity_conflict", f"entity does not exist: {operation.entity_id}")
            if entity.meta.status is EntityStatus.LOCKED or bool(entity.payload.get("user_modified")):
                raise MethodologyValidationError("identity_conflict", f"entity is locked or user modified: {operation.entity_id}")
