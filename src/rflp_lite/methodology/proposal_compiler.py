"""Validate semantic TaskProposals and compile them into canonical Patches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.domain.model import AddEntity, Deprecate, Patch, Relate, UpdateEntity
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.contracts import TaskExecutionRequest
from rflp_lite.methodology.policy import PatchPolicy


@dataclass(frozen=True, slots=True)
class ProposalEntity:
    local_ref: str
    kind: EntityKind
    name: str
    payload: Mapping[str, object]
    confidence: float | None = None
    source_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    lifecycle_ids: tuple[str, ...] = ()

    @property
    def ref(self) -> str:
        """Compatibility for internal callers; the wire field is local_ref."""

        return self.local_ref


@dataclass(frozen=True, slots=True)
class ProposalRelation:
    source_ref: str
    predicate: RelationPredicate
    target_ref: str
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProposalUpdate:
    entity_id: str
    field_patch: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ProposalDeprecation:
    entity_id: str


@dataclass(frozen=True, slots=True)
class TaskProposal:
    entities: tuple[ProposalEntity, ...]
    relations: tuple[ProposalRelation, ...]
    updates: tuple[ProposalUpdate, ...]
    deprecations: tuple[ProposalDeprecation, ...]
    reason: str


def proposal_schema(
    output_kinds: tuple[EntityKind, ...] | list[EntityKind] | set[EntityKind],
    schema_id: str,
    payload_schemas: Mapping[str, Mapping[str, object]],
    policy: PatchPolicy,
) -> dict[str, object]:
    """Build the provider-facing schema for one TaskProposal."""

    kind_values = sorted(kind.value for kind in output_kinds)
    entity_schema: dict[str, object] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["local_ref", "name", "payload"],
        "properties": {
            "local_ref": {"type": "string", "minLength": 1},
            "kind": {"enum": kind_values},
            "name": {"type": "string", "minLength": 1},
            "payload": {"type": "object"},
            "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
            "source_ids": {"type": "array", "items": {"type": "string"}},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
            "lifecycle_ids": {"type": "array", "items": {"type": "string"}},
        },
    }
    if len(kind_values) > 1:
        entity_schema["required"].append("kind")
    if len(kind_values) == 1:
        payload_schema = payload_schemas.get(kind_values[0])
        if isinstance(payload_schema, Mapping):
            entity_schema["properties"]["payload"] = dict(payload_schema)
    relation_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["source_ref", "predicate", "target_ref", "evidence_ids"],
        "properties": {
            "source_ref": {"type": "string", "minLength": 1},
            "predicate": {"enum": sorted(predicate.value for predicate in policy.allowed_predicates)},
            "target_ref": {"type": "string", "minLength": 1},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
        },
    }
    update_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["entity_id", "field_patch"],
        "properties": {
            "entity_id": {"type": "string", "minLength": 1},
            "field_patch": {"type": "object"},
        },
    }
    deprecation_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["entity_id"],
        "properties": {"entity_id": {"type": "string", "minLength": 1}},
    }
    field_schemas = {
        "name": {"type": "string"},
        "status": {"type": "string"},
        "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
        "payload": {"type": "object"},
        "lifecycle_ids": {"type": "array", "items": {"type": "string"}},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
    }
    field_patch_schema = {
        "type": "object",
        "additionalProperties": False,
        "minProperties": 1,
        "properties": {
            field: field_schemas.get(
                field,
                {"type": ["string", "number", "boolean", "array", "object", "null"]},
            )
            for field in sorted(policy.writable_fields)
        },
    }
    update_schema["properties"]["field_patch"] = field_patch_schema
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["entities", "relations", "updates", "deprecations", "reason"],
        "properties": {
            "entities": {"type": "array", "items": entity_schema, "maxItems": 32},
            "relations": {"type": "array", "items": relation_schema, "maxItems": 32},
            "updates": {"type": "array", "items": update_schema, "maxItems": 32},
            "deprecations": {"type": "array", "items": deprecation_schema, "maxItems": 32},
            "reason": {"type": "string", "maxLength": 300},
        },
        "schema_id": schema_id,
        "output_kinds": kind_values,
        "x-payload-schemas": {str(key): dict(value) for key, value in payload_schemas.items()},
        "patch_policy": {
            "writable_kinds": sorted(kind.value for kind in policy.writable_kinds),
            "writable_fields": sorted(policy.writable_fields),
            "allowed_predicates": sorted(predicate.value for predicate in policy.allowed_predicates),
            "max_operations": policy.max_operations,
        },
    }


def _effective_policy(request: TaskExecutionRequest, allowed_kinds: set[EntityKind]) -> PatchPolicy:
    policy = request.patch_policy
    if policy.writable_kinds:
        return policy
    return PatchPolicy(
        writable_kinds=frozenset(allowed_kinds),
        writable_fields=frozenset({"name", "status", "confidence", "payload", "lifecycle_ids", "evidence_ids"}),
        allowed_predicates=frozenset(RelationPredicate),
    )


def _string(value: object, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ContractViolation(f"task proposal field is required: {field}")
    return result


def _strings(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ContractViolation(f"task proposal field must be an array: {field}")
    return tuple(dict.fromkeys(_string(item, field) for item in value))


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ContractViolation(f"task proposal field must be an object: {field}")
    return dict(value)


def _arrays(payload: Mapping[str, object], field: str) -> list[Mapping[str, object]]:
    value = payload.get(field)
    if not isinstance(value, list):
        raise ContractViolation(f"task proposal field must be an array: {field}")
    result: list[Mapping[str, object]] = []
    for item in value:
        result.append(_mapping(item, field))
    return result


def _validate_schema(payload: Mapping[str, object], request: TaskExecutionRequest) -> None:
    schema = {
        key: value
        for key, value in request.output_contract.items()
        if key in {"type", "additionalProperties", "required", "properties", "allOf"}
    }
    if not schema:
        return
    try:
        from jsonschema import SchemaError, ValidationError, validate
        validate(dict(payload), schema)
    except ImportError as exc:
        raise ContractViolation("JSON schema validation is unavailable") from exc
    except ValidationError as exc:
        raise ContractViolation(f"task proposal schema is invalid: {exc.message}") from exc
    except SchemaError as exc:
        raise ContractViolation("task proposal schema is invalid") from exc


def _validate_entity_payload(kind: EntityKind, payload: Mapping[str, object], request: TaskExecutionRequest) -> None:
    schemas = request.output_contract.get("x-payload-schemas", {})
    schema = schemas.get(kind.value) if isinstance(schemas, Mapping) else None
    if not isinstance(schema, Mapping):
        return
    try:
        from jsonschema import SchemaError, ValidationError, validate
        validate(dict(payload), dict(schema))
    except ValidationError as exc:
        raise ContractViolation(f"invalid {kind.value} payload: {exc.message}") from exc
    except SchemaError as exc:
        raise ContractViolation(f"invalid {kind.value} payload schema") from exc


def parse_task_proposal(request: TaskExecutionRequest, payload: Mapping[str, object]) -> TaskProposal:
    """Parse and validate the semantic proposal before any Patch is created."""

    if "operations" in payload:
        raise ContractViolation("task proposal cannot contain operations")
    _validate_schema(payload, request)
    entities: list[ProposalEntity] = []
    refs: set[str] = set()
    try:
        allowed_kinds = {
            EntityKind(str(value))
            for value in request.output_contract.get("output_kinds", ())
        }
    except ValueError as exc:
        raise ContractViolation("task proposal output kind contract is invalid") from exc
    policy = _effective_policy(request, allowed_kinds)
    for raw in _arrays(payload, "entities"):
        local_ref = _string(raw.get("local_ref"), "entities.local_ref")
        if local_ref in refs:
            raise ContractViolation(f"duplicate task proposal local_ref: {local_ref}")
        refs.add(local_ref)
        try:
            raw_kind = raw.get("kind")
            if raw_kind is None and len(allowed_kinds) == 1:
                kind = next(iter(allowed_kinds))
            else:
                kind = EntityKind(_string(raw_kind, "entities.kind"))
        except ValueError as exc:
            raise ContractViolation("task proposal entity kind is invalid") from exc
        if kind not in allowed_kinds or kind not in policy.writable_kinds:
            raise ContractViolation(f"task cannot propose output kind: {kind.value}")
        entity_payload = _mapping(raw.get("payload"), "entities.payload")
        _validate_entity_payload(kind, entity_payload, request)
        confidence = raw.get("confidence")
        if confidence is not None:
            try:
                confidence = float(confidence)
            except (TypeError, ValueError) as exc:
                raise ContractViolation("task proposal confidence must be numeric") from exc
            if not 0.0 <= confidence <= 1.0:
                raise ContractViolation("task proposal confidence must be between 0 and 1")
        entities.append(ProposalEntity(
            local_ref=local_ref,
            kind=kind,
            name=_string(raw.get("name"), "entities.name"),
            payload=entity_payload,
            confidence=confidence,
            source_ids=_strings(raw.get("source_ids"), "entities.source_ids"),
            evidence_ids=_strings(raw.get("evidence_ids"), "entities.evidence_ids"),
            lifecycle_ids=_strings(raw.get("lifecycle_ids"), "entities.lifecycle_ids"),
        ))
    relations: list[ProposalRelation] = []
    for raw in _arrays(payload, "relations"):
        try:
            predicate = RelationPredicate(_string(raw.get("predicate"), "relations.predicate"))
        except ValueError as exc:
            raise ContractViolation("task proposal relation predicate is invalid") from exc
        if predicate not in policy.allowed_predicates:
            raise ContractViolation(f"task relation predicate is outside write scope: {predicate.value}")
        relations.append(ProposalRelation(
            source_ref=_string(raw.get("source_ref"), "relations.source_ref"),
            predicate=predicate,
            target_ref=_string(raw.get("target_ref"), "relations.target_ref"),
            evidence_ids=_strings(raw.get("evidence_ids"), "relations.evidence_ids"),
        ))
    updates: list[ProposalUpdate] = []
    for raw in _arrays(payload, "updates"):
        field_patch = _mapping(raw.get("field_patch"), "updates.field_patch")
        unknown = set(field_patch) - set(policy.writable_fields)
        if unknown:
            raise ContractViolation(f"task cannot update fields outside write scope: {sorted(unknown)}")
        updates.append(ProposalUpdate(_string(raw.get("entity_id"), "updates.entity_id"), field_patch))
    deprecations = tuple(
        ProposalDeprecation(_string(raw.get("entity_id"), "deprecations.entity_id"))
        for raw in _arrays(payload, "deprecations")
    )
    reason = _string(payload.get("reason"), "reason")[:300]
    return TaskProposal(tuple(entities), tuple(relations), tuple(updates), deprecations, reason)


def _resolve_ref(
    ref: str,
    ref_to_id: Mapping[str, str],
    context_entities: Mapping[str, object],
) -> str:
    if ref in ref_to_id:
        return ref_to_id[ref]
    if ref in context_entities:
        return ref
    raise ContractViolation(f"task proposal reference is unknown: {ref}")


def _in_scope(entity_id: str, context_entities: Mapping[str, object], output_ids: set[str], policy: PatchPolicy) -> bool:
    scope = policy.allowed_entity_scope
    if isinstance(scope, (set, frozenset, tuple, list)):
        return entity_id in scope
    if scope == "context":
        return entity_id in context_entities
    return entity_id in context_entities or entity_id in output_ids


def compile_task_proposal(request: TaskExecutionRequest, payload: Mapping[str, object]) -> Patch | None:
    """Validate one TaskProposal and compile it into a canonical Patch."""

    proposal = parse_task_proposal(request, payload)
    try:
        allowed_kinds = {
            EntityKind(str(value))
            for value in request.output_contract.get("output_kinds", ())
        }
    except ValueError as exc:
        raise ContractViolation("task proposal output kind contract is invalid") from exc
    policy = _effective_policy(request, allowed_kinds)
    context_entities = {item.id: item for item in request.context_bundle.entities}
    operations = []
    ref_to_id: dict[str, str] = {}
    output_ids: set[str] = set()
    for item in proposal.entities:
        entity = make_entity(
            item.kind,
            item.name,
            item.payload,
            status=EntityStatus.CANDIDATE,
            producer=Producer.LLM,
            confidence=item.confidence,
            source_ids=item.source_ids,
            evidence_ids=item.evidence_ids,
            lifecycle_ids=item.lifecycle_ids,
            revision=request.context_bundle.revision,
        )
        ref_to_id[item.local_ref] = entity.id
        output_ids.add(entity.id)
        operations.append(AddEntity(entity))
    for item in proposal.relations:
        source_id = _resolve_ref(item.source_ref, ref_to_id, context_entities)
        target_id = _resolve_ref(item.target_ref, ref_to_id, context_entities)
        if not _in_scope(source_id, context_entities, output_ids, policy) or not _in_scope(target_id, context_entities, output_ids, policy):
            raise ContractViolation("task proposal relation endpoint is outside write scope")
        operations.append(Relate(source_id, item.predicate, target_id, item.evidence_ids))
    for item in proposal.updates:
        entity = context_entities.get(item.entity_id)
        if entity is None or entity.kind not in policy.writable_kinds:
            raise ContractViolation(f"task cannot update entity outside write scope: {item.entity_id}")
        if "payload" in item.field_patch:
            payload_patch = _mapping(item.field_patch["payload"], "updates.field_patch.payload")
            _validate_entity_payload(entity.kind, payload_patch, request)
        operations.append(UpdateEntity(item.entity_id, item.field_patch))
    for item in proposal.deprecations:
        entity = context_entities.get(item.entity_id)
        if entity is None or entity.kind not in policy.writable_kinds:
            raise ContractViolation(f"task cannot deprecate entity outside write scope: {item.entity_id}")
        operations.append(Deprecate(item.entity_id))
    if policy.max_operations is not None and len(operations) > policy.max_operations:
        raise ContractViolation("task proposal exceeds operation limit")
    if not operations:
        return None
    return Patch.create(
        request.context_bundle.project_id,
        request.task_id,
        tuple(operations),
        proposal.reason,
        request.context_bundle.revision,
    )
