"""Convert a validated task envelope into the only AI write primitive."""

from __future__ import annotations

from dataclasses import replace
from typing import Mapping

from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.domain.model import AddEntity, Deprecate, Patch, Relate, UpdateEntity
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.contracts import TaskExecutionRequest


def _string(value: object, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ContractViolation(f"task patch field is required: {field}")
    return result


def _operations(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
    raw = payload.get("operations", ())
    if not isinstance(raw, list):
        raise ContractViolation("task output operations must be an array")
    result: list[Mapping[str, object]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ContractViolation("task output operation must be an object")
        result.append(item)
    return result


def patch_from_response(
    request: TaskExecutionRequest,
    payload: Mapping[str, object],
) -> Patch | None:
    """Build a Patch and reject operations outside the TaskSpec contract.

    An empty operation list is a valid no-change task result.  It is useful
    for already-covered tasks and keeps retries idempotent.
    """

    operations = []
    allowed_kinds = {
        EntityKind(str(value)) for value in request.output_contract.get("output_kinds", ())
    }
    for item in _operations(payload):
        op = _string(item.get("op"), "op").upper()
        if op == "ADD":
            kind = EntityKind(_string(item.get("kind"), "kind"))
            if kind not in allowed_kinds:
                raise ContractViolation(f"task cannot add output kind: {kind.value}")
            entity = make_entity(
                kind,
                _string(item.get("name"), "name"),
                item.get("payload") if isinstance(item.get("payload"), Mapping) else {},
                status=EntityStatus.CANDIDATE,
                producer=Producer.LLM,
                confidence=float(item["confidence"]) if item.get("confidence") is not None else None,
                source_ids=tuple(str(value) for value in item.get("source_ids", ()) if str(value)),
                evidence_ids=tuple(str(value) for value in item.get("evidence_ids", ()) if str(value)),
                lifecycle_ids=tuple(str(value) for value in item.get("lifecycle_ids", ()) if str(value)),
                revision=request.context_bundle.revision,
            )
            operations.append(AddEntity(entity))
        elif op == "UPDATE":
            operations.append(
                UpdateEntity(
                    _string(item.get("entity_id"), "entity_id"),
                    item.get("field_patch") if isinstance(item.get("field_patch"), Mapping) else {},
                )
            )
        elif op == "RELATE":
            try:
                predicate = RelationPredicate(_string(item.get("predicate"), "predicate"))
            except ValueError as exc:
                raise ContractViolation("task relation predicate is not allowlisted") from exc
            operations.append(
                Relate(
                    _string(item.get("source_id"), "source_id"),
                    predicate,
                    _string(item.get("target_id"), "target_id"),
                    tuple(str(value) for value in item.get("evidence_ids", ()) if str(value)),
                )
            )
        elif op == "DEPRECATE":
            operations.append(Deprecate(_string(item.get("entity_id"), "entity_id")))
        else:
            raise ContractViolation(f"unsupported task patch operation: {op}")
    if not operations:
        return None
    reason = str(payload.get("reason") or request.task_id).strip()[:300]
    return Patch.create(
        request.context_bundle.project_id,
        request.task_id,
        tuple(operations),
        reason,
        request.context_bundle.revision,
    )
