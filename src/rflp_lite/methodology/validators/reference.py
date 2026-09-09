"""Reference, predicate, and endpoint-kind checks over a prospective graph."""

from __future__ import annotations

from rflp_lite.domain.entities import Entity
from rflp_lite.domain.errors import MethodologyValidationError
from rflp_lite.domain.model import AddEntity, Relate
from rflp_lite.domain.relations import RelationPredicate, validate_endpoint_kinds
from rflp_lite.methodology.validation import ValidationContext


def validate(context: ValidationContext) -> None:
    patch = context.response.patch
    if patch is None:
        return
    entities: dict[str, Entity] = context.graph.entity_index
    for operation in patch.operations:
        if isinstance(operation, AddEntity):
            entities[operation.entity.id] = operation.entity
    for operation in patch.operations:
        if not isinstance(operation, Relate):
            continue
        source = entities.get(operation.source_id)
        target = entities.get(operation.target_id)
        if source is None or target is None:
            raise MethodologyValidationError(
                "reference_missing", f"relation endpoint not found: {operation.source_id} -> {operation.target_id}"
            )
        if not isinstance(operation.predicate, RelationPredicate):
            raise MethodologyValidationError("reference_missing", "relation predicate is not allowlisted")
        try:
            validate_endpoint_kinds(operation.predicate, source.kind, target.kind)
        except Exception as exc:
            raise MethodologyValidationError("relation_endpoint_invalid", str(exc)) from exc
