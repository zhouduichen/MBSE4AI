"""Evidence identifier checks for patch references."""

from __future__ import annotations

from collections.abc import Mapping

from rflp_lite.domain.errors import MethodologyValidationError
from rflp_lite.domain.model import AddEntity, Relate, UpdateEntity
from rflp_lite.methodology.validation import ValidationContext


def _evidence_ids(context: ValidationContext) -> set[str]:
    result = {
        str(item.get("id"))
        for item in context.context.evidence
        if isinstance(item, Mapping) and item.get("id")
    }
    for entity in context.graph.entities:
        result.update(entity.meta.evidence_ids)
    return result


def validate(context: ValidationContext) -> None:
    patch = context.response.patch
    if patch is None:
        return
    available = _evidence_ids(context)
    references: set[str] = set()
    for operation in patch.operations:
        if isinstance(operation, AddEntity):
            references.update(operation.entity.meta.evidence_ids)
        elif isinstance(operation, Relate):
            references.update(operation.evidence_ids)
        elif isinstance(operation, UpdateEntity):
            value = operation.field_patch.get("evidence_ids")
            if isinstance(value, (tuple, list)):
                references.update(str(item) for item in value)
    missing = sorted(item for item in references if item not in available)
    if missing:
        raise MethodologyValidationError("evidence_missing", f"evidence ids do not exist: {missing}")
