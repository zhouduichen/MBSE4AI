"""Add deterministic architecture evidence to task patches when needed."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from rflp_lite.domain.entities import Entity, EntityKind, EntityStatus
from rflp_lite.domain.model import AddEntity, ModelGraph, Patch, Relate, UpdateEntity, apply_patch
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.architecture_reasoning import (
    logical_reasoning_payload,
    physical_reasoning_payload,
)
from rflp_lite.methodology.architecture_synthesis import synthesize_architecture


_ARCHITECTURE_TASK_KINDS = {
    "logical_analysis": (EntityKind.LOGICAL_COMPONENT, "architecture_reasoning"),
    "physical_candidates": (EntityKind.PHYSICAL_BLOCK, "feasibility_reasoning"),
    "vertical.logical": (EntityKind.LOGICAL_COMPONENT, "architecture_reasoning"),
    "vertical.physical": (EntityKind.PHYSICAL_BLOCK, "feasibility_reasoning"),
}


def enrich_architecture_patch(graph: ModelGraph, patch: Patch) -> Patch:
    """Fill missing architecture evidence without replacing model output.

    The enrichment is deterministic and runs on the post-patch preview.  It
    only targets Logical/Physical entities touched by the task, preserves a
    non-empty field supplied by an LLM, and skips protected human anchors.
    """

    contract = _ARCHITECTURE_TASK_KINDS.get(patch.task_id)
    if contract is None:
        return patch
    kind, field = contract
    preview = apply_patch(graph, patch)
    target_ids = _touched_ids(graph, preview, patch, kind)
    if not target_ids:
        return patch
    synthesis = synthesize_architecture(preview)
    reasoning_by_id: dict[str, Mapping[str, object]] = {}
    if kind is EntityKind.LOGICAL_COMPONENT:
        functions = tuple(
            item for item in preview.entities if item.kind is EntityKind.FUNCTION
        )
        names = {item.id: item.meta.name for item in functions}
        for entity_id in target_ids:
            entity = preview.entity_index[entity_id]
            if _has_reasoning(entity, field) or _protected(entity):
                continue
            function_ids = _functions_for_component(preview, entity, functions)
            grouped = tuple(item for item in functions if item.id in function_ids)
            reasoning_by_id[entity_id] = logical_reasoning_payload(
                synthesis,
                function_ids=function_ids,
                functional_flow_ids=_flows_for_functions(preview, function_ids),
                dependency_pairs=_dependency_pairs(grouped),
                shared_state=_payload_values(grouped, "shared_state"),
                timing_constraints=_payload_values(grouped, "timing_constraints"),
                safety_isolation=(
                    _payload_values(grouped, "safety_isolation")
                    + _payload_values(grouped, "safety_constraints")
                ),
                selection_status="needs_review",
                names=names,
            )
    else:
        rows = {
            row.physical_id: row
            for row in synthesis.physical_rows
        }
        for entity_id in target_ids:
            entity = preview.entity_index[entity_id]
            row = rows.get(entity_id)
            if row is None or _has_reasoning(entity, field) or _protected(entity):
                continue
            reasoning_by_id[entity_id] = physical_reasoning_payload(row)
    return _with_reasoning(patch, reasoning_by_id, field)


def _touched_ids(
    graph: ModelGraph,
    preview: ModelGraph,
    patch: Patch,
    kind: EntityKind,
) -> tuple[str, ...]:
    current = graph.entity_index
    ids: set[str] = set()
    for operation in patch.operations:
        if isinstance(operation, AddEntity) and operation.entity.kind is kind:
            ids.add(operation.entity.id)
        elif isinstance(operation, UpdateEntity):
            entity = current.get(operation.entity_id)
            if entity is not None and entity.kind is kind:
                ids.add(operation.entity_id)
        elif isinstance(operation, Relate):
            for entity_id in (operation.source_id, operation.target_id):
                entity = preview.entity_index.get(entity_id)
                if entity is not None and entity.kind is kind:
                    ids.add(entity_id)
    return tuple(sorted(ids))


def _with_reasoning(
    patch: Patch,
    reasoning_by_id: Mapping[str, Mapping[str, object]],
    field: str,
) -> Patch:
    if not reasoning_by_id:
        return patch
    operations = list(patch.operations)
    touched = set(reasoning_by_id)
    for index, operation in enumerate(operations):
        entity_id = _operation_entity_id(operation)
        if entity_id not in touched:
            continue
        reasoning = reasoning_by_id[entity_id]
        if isinstance(operation, AddEntity):
            operations[index] = AddEntity(
                replace(
                    operation.entity,
                    payload={**dict(operation.entity.payload), field: dict(reasoning)},
                )
            )
            touched.remove(entity_id)
        elif isinstance(operation, UpdateEntity):
            field_patch = dict(operation.field_patch)
            payload = field_patch.get("payload")
            merged = dict(payload) if isinstance(payload, Mapping) else {}
            merged[field] = dict(reasoning)
            field_patch["payload"] = merged
            operations[index] = UpdateEntity(operation.entity_id, field_patch)
            touched.remove(entity_id)
    if touched:
        operations.extend(
            UpdateEntity(entity_id, {"payload": {field: dict(reasoning_by_id[entity_id])}})
            for entity_id in sorted(touched)
            if len(operations) < 32
        )
    if tuple(operations) == patch.operations:
        return patch
    return Patch.create(
        patch.project_id,
        patch.task_id,
        tuple(operations),
        patch.reason,
        patch.expected_revision,
    )


def _operation_entity_id(operation: object) -> str:
    if isinstance(operation, AddEntity):
        return operation.entity.id
    if isinstance(operation, UpdateEntity):
        return operation.entity_id
    return ""


def _has_reasoning(entity: Entity, field: str) -> bool:
    value = entity.payload.get(field)
    if not isinstance(value, Mapping) or not value:
        return False
    if field == "architecture_reasoning":
        basis = value.get("basis")
        return (
            isinstance(basis, Mapping)
            and isinstance(value.get("alternatives"), (list, tuple))
            and bool(str(value.get("recommended_alternative", "")).strip())
            and bool(str(value.get("selection_status", "")).strip())
        )
    if field == "feasibility_reasoning":
        return all(
            key in value
            for key in (
                "requirement_ids", "logical_ids", "function_ids",
                "propagated_constraints", "missing_fields", "conflicts",
                "status", "score", "resolution_options",
            )
        )
    return True


def _protected(entity: Entity) -> bool:
    return (
        entity.meta.status is EntityStatus.LOCKED
        or bool(entity.payload.get("user_modified"))
    )


def _functions_for_component(
    graph: ModelGraph,
    logical: Entity,
    functions: tuple[Entity, ...],
) -> tuple[str, ...]:
    payload_function_id = str(logical.payload.get("function_id", "")).strip()
    assigned = {
        relation.source_id
        for relation in graph.relations
        if relation.target_id == logical.id
        and relation.predicate is RelationPredicate.ALLOCATED_TO
    }
    return tuple(
        item.id
        for item in functions
        if item.id == payload_function_id or item.id in assigned
    )


def _flows_for_functions(graph: ModelGraph, function_ids: tuple[str, ...]) -> tuple[str, ...]:
    selected = set(function_ids)
    return tuple(
        item.id
        for item in graph.entities
        if item.kind is EntityKind.FUNCTIONAL_FLOW
        and selected.intersection(
            set(_payload_refs(item.payload, "source_function_ids"))
            | set(_payload_refs(item.payload, "target_function_ids"))
        )
    )


def _dependency_pairs(functions: tuple[Entity, ...]) -> tuple[tuple[str, str], ...]:
    function_ids = {item.id for item in functions}
    pairs: set[tuple[str, str]] = set()
    for function in functions:
        for field in ("dependencies", "dependency_ids", "depends_on", "depends_on_ids"):
            for target_id in _payload_refs(function.payload, field):
                if target_id in function_ids and target_id != function.id:
                    pairs.add(tuple(sorted((function.id, target_id))))
    return tuple(sorted(pairs))


def _payload_values(entities: tuple[Entity, ...], field: str) -> list[object]:
    values: list[object] = []
    for entity in entities:
        raw = entity.payload.get(field, ())
        if isinstance(raw, (list, tuple, set)):
            values.extend(raw)
        elif raw not in (None, ""):
            values.append(raw)
    return [
        value
        for index, value in enumerate(values)
        if value not in values[:index]
    ]


def _payload_refs(payload: Mapping[str, object], field: str) -> tuple[str, ...]:
    raw = payload.get(field, ())
    if isinstance(raw, (list, tuple, set)):
        values = raw
    elif raw in (None, ""):
        values = ()
    else:
        values = (raw,)
    return tuple(
        dict.fromkeys(
            str(value).strip() for value in values if str(value).strip()
        )
    )
