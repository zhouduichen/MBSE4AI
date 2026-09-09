"""Immutable ModelGraph revisions and the only AI write path."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.entities import Entity, EntityStatus
from rflp_lite.domain.errors import ConcurrentModificationError, ContractViolation
from rflp_lite.domain.relations import RelationPredicate, validate_endpoint_kinds


@dataclass(frozen=True, slots=True)
class Relation:
    id: str
    source_id: str
    predicate: RelationPredicate
    target_id: str
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelGraph:
    project_id: str
    entities: tuple[Entity, ...] = ()
    relations: tuple[Relation, ...] = ()
    revision: int = 0

    def __post_init__(self) -> None:
        if self.revision < 0:
            raise ValueError("revision cannot be negative")
        ids = [item.id for item in self.entities]
        if len(ids) != len(set(ids)):
            raise ContractViolation("entity id duplicated")
        relation_ids = [item.id for item in self.relations]
        if len(relation_ids) != len(set(relation_ids)):
            raise ContractViolation("relation id duplicated")

    @property
    def entity_index(self) -> dict[str, Entity]:
        return {item.id: item for item in self.entities}

    @property
    def snapshot_hash(self) -> str:
        return canonical_hash({
            "project_id": self.project_id,
            "revision": self.revision,
            "entities": [item.as_dict() for item in self.entities],
            "relations": [item.__dict__ if hasattr(item, "__dict__") else {
                "id": item.id, "source_id": item.source_id,
                "predicate": item.predicate.value, "target_id": item.target_id,
                "evidence_ids": item.evidence_ids,
            } for item in self.relations],
        })

    def validate_relation(self, relation: Relation) -> None:
        index = self.entity_index
        source = index.get(relation.source_id)
        target = index.get(relation.target_id)
        if source is None or target is None:
            raise ContractViolation(f"relation endpoint not found: {relation.source_id} -> {relation.target_id}")
        validate_endpoint_kinds(relation.predicate, source.kind, target.kind)


@dataclass(frozen=True, slots=True)
class AddEntity:
    entity: Entity


@dataclass(frozen=True, slots=True)
class UpdateEntity:
    entity_id: str
    field_patch: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class Relate:
    source_id: str
    predicate: RelationPredicate
    target_id: str
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Deprecate:
    entity_id: str


PatchOperation = AddEntity | UpdateEntity | Relate | Deprecate


@dataclass(frozen=True, slots=True)
class Patch:
    id: str
    project_id: str
    task_id: str
    operations: tuple[PatchOperation, ...]
    reason: str
    expected_revision: int

    @classmethod
    def create(
        cls,
        project_id: str,
        task_id: str,
        operations: tuple[PatchOperation, ...],
        reason: str,
        expected_revision: int,
    ) -> "Patch":
        identity = (project_id, task_id, operations, reason, expected_revision)
        return cls(f"patch-{canonical_hash(identity)[:16]}", project_id, task_id, operations, reason, expected_revision)


@dataclass(frozen=True, slots=True)
class Revision:
    project_id: str
    sequence: int
    parent_id: str | None
    reason: str
    snapshot_hash: str
    run_id: str | None = None


def apply_patch(graph: ModelGraph, patch: Patch) -> ModelGraph:
    if patch.project_id != graph.project_id:
        raise ContractViolation("patch project does not match graph project")
    if patch.expected_revision != graph.revision:
        raise ConcurrentModificationError(
            f"stale ModelGraph revision: expected {patch.expected_revision}, current {graph.revision}"
        )
    entities = graph.entity_index
    relations = {item.id: item for item in graph.relations}
    next_revision = graph.revision + 1
    for operation in patch.operations:
        if isinstance(operation, AddEntity):
            if operation.entity.id in entities:
                raise ContractViolation(f"entity already exists: {operation.entity.id}")
            entities[operation.entity.id] = Entity(
                replace(
                    operation.entity.meta,
                    created_revision=next_revision,
                    updated_revision=next_revision,
                ),
                operation.entity.payload,
            )
        elif isinstance(operation, UpdateEntity):
            entity = entities.get(operation.entity_id)
            if entity is None:
                raise ContractViolation(f"entity not found: {operation.entity_id}")
            if entity.meta.status is EntityStatus.LOCKED or bool(entity.payload.get("user_modified")):
                raise ContractViolation(f"entity is locked: {operation.entity_id}")
            allowed = {"name", "status", "confidence", "payload", "lifecycle_ids", "evidence_ids"}
            unknown = set(operation.field_patch) - allowed
            if unknown:
                raise ContractViolation(f"unsupported entity patch fields: {sorted(unknown)}")
            meta = entity.meta
            if "name" in operation.field_patch:
                meta = replace(meta, name=str(operation.field_patch["name"]))
            if "status" in operation.field_patch:
                try:
                    meta = replace(meta, status=EntityStatus(str(operation.field_patch["status"])))
                except ValueError as exc:
                    raise ContractViolation("unsupported entity status") from exc
            if "confidence" in operation.field_patch:
                confidence = operation.field_patch["confidence"]
                meta = replace(meta, confidence=float(confidence) if confidence is not None else None)
            if "lifecycle_ids" in operation.field_patch:
                value = operation.field_patch["lifecycle_ids"]
                if not isinstance(value, (list, tuple)):
                    raise ContractViolation("lifecycle_ids patch must be an array")
                meta = replace(meta, lifecycle_ids=tuple(str(item) for item in value))
            if "evidence_ids" in operation.field_patch:
                value = operation.field_patch["evidence_ids"]
                if not isinstance(value, (list, tuple)):
                    raise ContractViolation("evidence_ids patch must be an array")
                meta = replace(meta, evidence_ids=tuple(str(item) for item in value))
            payload = dict(entity.payload)
            if "payload" in operation.field_patch:
                value = operation.field_patch["payload"]
                if not isinstance(value, Mapping):
                    raise ContractViolation("entity payload patch must be an object")
                payload.update(value)
            entities[operation.entity_id] = Entity(
                replace(meta, updated_revision=next_revision), payload
            )
        elif isinstance(operation, Deprecate):
            entity = entities.get(operation.entity_id)
            if entity is None:
                raise ContractViolation(f"entity not found: {operation.entity_id}")
            if entity.meta.status is EntityStatus.LOCKED:
                raise ContractViolation(f"entity is locked: {operation.entity_id}")
            meta = replace(entity.meta, status=EntityStatus.DEPRECATED, updated_revision=next_revision)
            entities[operation.entity_id] = Entity(meta, entity.payload)
        else:
            relation_identity = (operation.source_id, operation.predicate.value, operation.target_id)
            relation_id = f"rel-{canonical_hash(relation_identity)[:16]}"
            relations[relation_id] = Relation(
                relation_id, operation.source_id, operation.predicate,
                operation.target_id, operation.evidence_ids,
            )
    next_graph = ModelGraph(graph.project_id, tuple(sorted(entities.values(), key=lambda item: item.id)), tuple(sorted(relations.values(), key=lambda item: item.id)), next_revision)
    for relation in next_graph.relations:
        next_graph.validate_relation(relation)
    return next_graph
