"""Convert a validated task envelope into the only AI write primitive."""

from __future__ import annotations

from dataclasses import replace
from typing import Mapping

from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.domain.model import AddEntity, Deprecate, Patch, Relate, UpdateEntity
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.contracts import TaskExecutionRequest
from rflp_lite.methodology.policy import PatchPolicy


def _effective_policy(request: TaskExecutionRequest, allowed_kinds: set[EntityKind]) -> PatchPolicy:
    policy = request.patch_policy
    if policy.writable_kinds:
        return policy
    # Backwards-compatible requests created before PatchPolicy was added.
    return PatchPolicy(
        writable_kinds=frozenset(allowed_kinds),
        writable_fields=frozenset({"name", "status", "confidence", "payload", "lifecycle_ids", "evidence_ids"}),
        allowed_predicates=frozenset(RelationPredicate),
    )


def _validate_payload(kind: EntityKind, payload: object, request: TaskExecutionRequest) -> None:
    if not isinstance(payload, Mapping):
        raise ContractViolation("task ADD payload must be an object")
    schemas = request.output_contract.get("x-payload-schemas", {})
    schema = schemas.get(kind.value) if isinstance(schemas, Mapping) else None
    if not isinstance(schema, Mapping):
        return
    try:
        from jsonschema import ValidationError, validate
        validate(dict(payload), dict(schema))
    except ValidationError as exc:
        raise ContractViolation(f"invalid {kind.value} payload: {exc.message}") from exc


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
    policy = _effective_policy(request, allowed_kinds)
    context_entities = {item.id: item for item in request.context_bundle.entities}
    output_ids: set[str] = set()
    for item in _operations(payload):
        op = _string(item.get("op"), "op").upper()
        if op == "ADD":
            kind = EntityKind(_string(item.get("kind"), "kind"))
            if kind not in allowed_kinds or kind not in policy.writable_kinds:
                raise ContractViolation(f"task cannot add output kind: {kind.value}")
            raw_payload = item.get("payload") if isinstance(item.get("payload"), Mapping) else {}
            _validate_payload(kind, raw_payload, request)
            entity = make_entity(
                kind,
                _string(item.get("name"), "name"),
                raw_payload,
                status=EntityStatus.CANDIDATE,
                producer=Producer.LLM,
                confidence=float(item["confidence"]) if item.get("confidence") is not None else None,
                source_ids=tuple(str(value) for value in item.get("source_ids", ()) if str(value)),
                evidence_ids=tuple(str(value) for value in item.get("evidence_ids", ()) if str(value)),
                lifecycle_ids=tuple(str(value) for value in item.get("lifecycle_ids", ()) if str(value)),
                revision=request.context_bundle.revision,
            )
            operations.append(AddEntity(entity))
            output_ids.add(entity.id)
        elif op == "UPDATE":
            entity_id = _string(item.get("entity_id"), "entity_id")
            entity = context_entities.get(entity_id)
            if entity is None or entity.kind not in policy.writable_kinds:
                raise ContractViolation(f"task cannot update entity outside write scope: {entity_id}")
            field_patch = item.get("field_patch") if isinstance(item.get("field_patch"), Mapping) else {}
            unknown_fields = set(field_patch) - set(policy.writable_fields)
            if unknown_fields:
                raise ContractViolation(f"task cannot update fields outside write scope: {sorted(unknown_fields)}")
            if "payload" in field_patch:
                _validate_payload(entity.kind, field_patch["payload"], request)
            operations.append(
                UpdateEntity(
                    entity_id,
                    field_patch,
                )
            )
        elif op == "RELATE":
            try:
                predicate = RelationPredicate(_string(item.get("predicate"), "predicate"))
            except ValueError as exc:
                raise ContractViolation("task relation predicate is not allowlisted") from exc
            if predicate not in policy.allowed_predicates:
                raise ContractViolation(f"task relation predicate is outside write scope: {predicate.value}")
            source_id = _string(item.get("source_id"), "source_id")
            target_id = _string(item.get("target_id"), "target_id")
            if not _in_scope(source_id, context_entities, output_ids, policy) or not _in_scope(target_id, context_entities, output_ids, policy):
                raise ContractViolation("task relation endpoint is outside write scope")
            operations.append(
                Relate(
                    source_id,
                    predicate,
                    target_id,
                    tuple(str(value) for value in item.get("evidence_ids", ()) if str(value)),
                )
            )
        elif op == "DEPRECATE":
            entity_id = _string(item.get("entity_id"), "entity_id")
            entity = context_entities.get(entity_id)
            if entity is None or entity.kind not in policy.writable_kinds:
                raise ContractViolation(f"task cannot deprecate entity outside write scope: {entity_id}")
            operations.append(Deprecate(entity_id))
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


def _in_scope(
    entity_id: str,
    context_entities: Mapping[str, object],
    output_ids: set[str],
    policy: PatchPolicy,
) -> bool:
    scope = policy.allowed_entity_scope
    if isinstance(scope, (set, frozenset, tuple, list)):
        return entity_id in scope
    if scope == "context":
        return entity_id in context_entities
    return entity_id in context_entities or entity_id in output_ids
