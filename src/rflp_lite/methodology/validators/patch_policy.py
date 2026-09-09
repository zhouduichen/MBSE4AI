"""Enforce TaskSpec write authority immediately before Repository CAS."""

from __future__ import annotations

from rflp_lite.domain.errors import MethodologyValidationError
from rflp_lite.domain.model import AddEntity, Deprecate, Relate, UpdateEntity
from rflp_lite.methodology.validation import ValidationContext


def _scope(context: ValidationContext, added: set[str]) -> set[str] | None:
    scope = context.task.patch_policy.allowed_entity_scope
    if isinstance(scope, (set, frozenset, tuple, list)):
        return {str(item) for item in scope}
    if scope == "context":
        return {item.id for item in context.context.entities}
    return {item.id for item in context.context.entities} | added


def validate(context: ValidationContext) -> None:
    patch = context.response.patch
    if patch is None:
        return
    policy = context.task.patch_policy
    if policy.max_operations is not None and len(patch.operations) > policy.max_operations:
        raise MethodologyValidationError("patch_policy_violation", f"patch exceeds max operations: {policy.max_operations}")
    current = context.graph.entity_index
    added = {operation.entity.id for operation in patch.operations if isinstance(operation, AddEntity)}
    scope = _scope(context, added)
    for operation in patch.operations:
        if isinstance(operation, AddEntity):
            if operation.entity.kind not in policy.writable_kinds:
                raise MethodologyValidationError("patch_policy_violation", f"kind is not writable: {operation.entity.kind.value}")
        elif isinstance(operation, (UpdateEntity, Deprecate)):
            entity = current.get(operation.entity_id)
            if entity is None or entity.kind not in policy.writable_kinds:
                raise MethodologyValidationError("patch_policy_violation", f"entity is outside write scope: {operation.entity_id}")
            if isinstance(operation, UpdateEntity):
                fields = set(operation.field_patch)
                unknown = fields - set(policy.writable_fields)
                if unknown:
                    raise MethodologyValidationError("patch_policy_violation", f"fields are outside write scope: {sorted(unknown)}")
        elif isinstance(operation, Relate):
            if operation.predicate not in policy.allowed_predicates:
                raise MethodologyValidationError("patch_policy_violation", f"predicate is outside write scope: {operation.predicate.value}")
            if scope is not None and (operation.source_id not in scope or operation.target_id not in scope):
                raise MethodologyValidationError("patch_policy_violation", "relation endpoint is outside write scope")
