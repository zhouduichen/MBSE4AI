"""Add deterministic architecture evidence to task patches when needed."""

from __future__ import annotations

import json
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


def enrich_vertical_patch(graph: ModelGraph, patch: Patch) -> Patch:
    """Close deterministic typed gaps in a Provider vertical proposal.

    This is intentionally narrower than the offline completion bridge: it
    only derives fields and relations from entities already present in the
    proposal or graph.  The Provider remains responsible for selecting the
    functional, logical, physical, and assurance content.
    """

    if patch.task_id == "vertical.functional":
        return _enrich_functional_closure(graph, patch)
    if patch.task_id == "vertical.logical":
        patch = enrich_architecture_patch(graph, patch)
        return _enrich_logical_closure(graph, patch)
    if patch.task_id == "vertical.physical":
        patch = enrich_architecture_patch(graph, patch)
        return _enrich_physical_closure(graph, patch)
    return patch


def _enrich_functional_closure(graph: ModelGraph, patch: Patch) -> Patch:
    """Materialize legacy behavior text as a typed decomposition seed."""

    preview = apply_patch(graph, patch)
    payloads: dict[str, Mapping[str, object]] = {}
    relations: list[Relate] = []
    for function in _active_of_kind(preview, EntityKind.FUNCTION):
        if function.payload.get("decomposition"):
            value = None
        else:
            seed = function.payload.get("purpose") or function.payload.get("behavior")
            if isinstance(seed, (list, tuple)):
                value = list(seed)
            elif str(seed or "").strip():
                value = str(seed).strip()
            else:
                value = None
        if value is not None:
            payloads[function.id] = {"decomposition": value}
    for flow in _active_of_kind(preview, EntityKind.FUNCTIONAL_FLOW):
        function_ids = _payload_refs(flow.payload, "source_function_ids") + _payload_refs(
            flow.payload, "target_function_ids"
        )
        for function_id in function_ids:
            if (
                function_id in preview.entity_index
                and preview.entity_index[function_id].kind is EntityKind.FUNCTION
                and _relation_missing(
                    preview,
                    function_id,
                    RelationPredicate.EXCHANGES_WITH,
                    flow.id,
                )
            ):
                relations.append(
                    Relate(function_id, RelationPredicate.EXCHANGES_WITH, flow.id)
                )
    enriched = _merge_entity_payloads(graph, patch, payloads)
    return _append_operations(enriched, relations)


def _enrich_logical_closure(graph: ModelGraph, patch: Patch) -> Patch:
    preview = apply_patch(graph, patch)
    synthesis = synthesize_architecture(preview)
    candidate = synthesis.logical_candidates[0] if synthesis.logical_candidates else None
    payload_updates: dict[str, Mapping[str, object]] = {}
    relations: list[Relate] = []
    names = {
        item.id: item.meta.name
        for item in preview.entities
        if item.kind is EntityKind.FUNCTION
    }
    for component in _active_of_kind(preview, EntityKind.LOGICAL_COMPONENT):
        if _protected(component):
            continue
        function_ids = _functions_for_component(
            preview,
            component,
            tuple(item for item in preview.entities if item.kind is EntityKind.FUNCTION),
        )
        grouped = tuple(
            item for item in preview.entities
            if item.kind is EntityKind.FUNCTION and item.id in function_ids
        )
        reasoning = logical_reasoning_payload(
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
        payload = _logical_missing_fields(component, reasoning, candidate, function_ids)
        if payload:
            payload_updates[component.id] = payload
        for function_id in function_ids:
            if _relation_missing(
                preview,
                function_id,
                RelationPredicate.ALLOCATED_TO,
                component.id,
            ):
                relations.append(
                    Relate(function_id, RelationPredicate.ALLOCATED_TO, component.id)
                )
        for interface_id in _payload_refs(
            component.payload, "interface_ids"
        ):
            if _relation_missing(
                preview,
                component.id,
                RelationPredicate.CONNECTED_TO,
                interface_id,
            ):
                relations.append(
                    Relate(component.id, RelationPredicate.CONNECTED_TO, interface_id)
                )
    for interface in _active_of_kind(preview, EntityKind.INTERFACE):
        for component_id in _payload_refs(interface.payload, "connected_component_ids"):
            if _relation_missing(
                preview,
                component_id,
                RelationPredicate.CONNECTED_TO,
                interface.id,
            ):
                relations.append(
                    Relate(component_id, RelationPredicate.CONNECTED_TO, interface.id)
                )
    for state in _active_of_kind(preview, EntityKind.STATE):
        owner_id = str(state.payload.get("owner_id", "")).strip()
        if owner_id and _relation_missing(
            preview,
            owner_id,
            RelationPredicate.DECOMPOSES,
            state.id,
        ):
            relations.append(Relate(owner_id, RelationPredicate.DECOMPOSES, state.id))
    if not payload_updates and not relations:
        return patch
    enriched = _merge_entity_payloads(graph, patch, payload_updates)
    return _append_operations(enriched, relations)


def _logical_missing_fields(
    component: Entity,
    reasoning: Mapping[str, object],
    candidate,
    function_ids: tuple[str, ...],
) -> Mapping[str, object]:
    payload = {}
    if not _has_reasoning(component, "architecture_reasoning"):
        payload["architecture_reasoning"] = dict(reasoning)
    basis = reasoning.get("basis", {})
    if not str(component.payload.get("partition_basis", "")).strip():
        payload["partition_basis"] = json.dumps(basis, ensure_ascii=False, sort_keys=True)
    if not component.payload.get("dependencies"):
        payload["dependencies"] = list(function_ids)
    for field in ("shared_state", "timing_constraints", "safety_isolation"):
        if field not in component.payload:
            raw = basis.get(field, ()) if isinstance(basis, Mapping) else ()
            payload[field] = list(raw) if isinstance(raw, (list, tuple)) else []
    if candidate is not None:
        if not str(component.payload.get("cohesion", "")).strip():
            payload["cohesion"] = candidate.cohesion
        if not str(component.payload.get("coupling", "")).strip():
            payload["coupling"] = candidate.coupling
        if not str(component.payload.get("architecture_rationale", "")).strip():
            payload["architecture_rationale"] = candidate.rationale
    return payload


def _enrich_physical_closure(graph: ModelGraph, patch: Patch) -> Patch:
    preview = apply_patch(graph, patch)
    synthesis = synthesize_architecture(preview)
    rows = {row.physical_id: row for row in synthesis.physical_rows}
    payload_updates: dict[str, Mapping[str, object]] = {}
    relations: list[Relate] = []
    for physical in _active_of_kind(preview, EntityKind.PHYSICAL_BLOCK):
        row = rows.get(physical.id)
        if row is None or _protected(physical):
            continue
        payload = _physical_missing_fields(
            physical,
            row,
            no_explicit_constraints=not _has_explicit_constraints(preview),
        )
        if payload:
            payload_updates[physical.id] = payload
        for requirement_id in row.requirement_ids:
            if _relation_missing(
                preview,
                requirement_id,
                RelationPredicate.SATISFIED_BY,
                physical.id,
            ):
                relations.append(
                    Relate(requirement_id, RelationPredicate.SATISFIED_BY, physical.id)
                )
    if not payload_updates and not relations:
        return patch
    enriched = _merge_entity_payloads(graph, patch, payload_updates)
    return _append_operations(enriched, relations)


def _physical_missing_fields(
    physical: Entity,
    row,
    *,
    no_explicit_constraints: bool,
) -> Mapping[str, object]:
    current = physical.payload
    payload = {}
    aliases = {
        "mass_kg": "mass",
        "power_w": "average_power",
    }
    for target, source in aliases.items():
        if target not in current:
            payload[target] = current.get(source)
    if "endurance_h" not in current:
        energy = _number(current.get("energy"))
        power = _number(current.get("average_power"))
        payload["endurance_h"] = round(energy / power, 6) if energy is not None and power and power > 0 else None
    if not str(current.get("candidate_type", "")).strip():
        payload["candidate_type"] = "existing_imported_candidate"
    if no_explicit_constraints and "technical_requirement_status" not in current:
        payload["technical_requirement_status"] = "no_explicit_constraints"
    if "source_requirement_ids" not in current:
        payload["source_requirement_ids"] = list(row.requirement_ids)
    if "source_logical_ids" not in current:
        payload["source_logical_ids"] = list(row.logical_ids)
    if "source_function_ids" not in current:
        payload["source_function_ids"] = list(row.function_ids)
    if "propagated_constraints" not in current:
        payload["propagated_constraints"] = dict(row.propagated_constraints)
    if "propagated_constraint_provenance" not in current:
        payload["propagated_constraint_provenance"] = [
            {"requirement_id": item, "source": "ModelGraph requirement constraint"}
            for item in row.requirement_ids
        ]
    if "trade_study" not in current:
        payload["trade_study"] = {
            "alternatives": ["retain_current_candidate", "replace_candidate"],
            "decision_status": "needs_review",
            "criteria": ["requirement coverage", "SWaP-C", "interface compatibility"],
        }
    if "alternatives" not in current:
        payload["alternatives"] = ["retain_current_candidate", "replace_candidate"]
    if not str(current.get("selection_rationale", "")).strip():
        payload["selection_rationale"] = "依据约束传播、测量缺口和可行性状态保留候选，等待工程评审。"
    if not isinstance(current.get("feasibility"), Mapping):
        payload["feasibility"] = {
            "status": row.status,
            "score": row.score,
            "missing_fields": list(row.missing_fields),
            "conflicts": [dict(item) for item in row.conflicts],
        }
    if not _has_reasoning(physical, "feasibility_reasoning"):
        payload["feasibility_reasoning"] = dict(physical_reasoning_payload(row))
    if "impact_chain" not in current:
        payload["impact_chain"] = {
            "requirement_ids": list(row.requirement_ids),
            "function_ids": list(row.function_ids),
            "logical_ids": list(row.logical_ids),
            "physical_ids": [physical.id],
        }
    if "resolution_options" not in current:
        payload["resolution_options"] = [dict(item) for item in row.resolution_options]
    return payload


def _active_of_kind(graph: ModelGraph, kind: EntityKind) -> tuple[Entity, ...]:
    return tuple(
        item for item in graph.entities
        if item.kind is kind and item.meta.status not in {
            EntityStatus.REJECTED,
            EntityStatus.DEPRECATED,
        }
    )


def _has_explicit_constraints(graph: ModelGraph) -> bool:
    return any(
        bool(item.payload.get("constraints"))
        or any(str(key).startswith(("max_", "min_")) for key in item.payload)
        for item in _active_of_kind(graph, EntityKind.REQUIREMENT)
        if str(item.payload.get("level", "")).lower() != "technical"
    )


def _relation_missing(
    graph: ModelGraph,
    source_id: str,
    predicate: RelationPredicate,
    target_id: str,
) -> bool:
    return not any(
        item.source_id == source_id
        and item.predicate is predicate
        and item.target_id == target_id
        for item in graph.relations
    )


def _append_operations(patch: Patch, operations: list[object]) -> Patch:
    existing = list(patch.operations)
    remaining = max(0, 32 - len(existing))
    if remaining <= 0:
        return patch
    return Patch.create(
        patch.project_id,
        patch.task_id,
        tuple([*existing, *operations[:remaining]]),
        patch.reason,
        patch.expected_revision,
    )


def _merge_entity_payloads(
    graph: ModelGraph,
    patch: Patch,
    payloads: Mapping[str, Mapping[str, object]],
) -> Patch:
    """Merge derived fields into adds and update only entities in the base graph."""

    if not payloads:
        return patch
    operations = list(patch.operations)
    remaining = dict(payloads)
    for index, operation in enumerate(operations):
        if not isinstance(operation, AddEntity) or operation.entity.id not in remaining:
            continue
        entity = operation.entity
        operations[index] = AddEntity(
            replace(entity, payload={**dict(entity.payload), **dict(remaining.pop(entity.id))})
        )
    for entity_id, payload in remaining.items():
        if entity_id in graph.entity_index and len(operations) < 32:
            operations.append(UpdateEntity(entity_id, {"payload": dict(payload)}))
    if tuple(operations) == patch.operations:
        return patch
    return Patch.create(
        patch.project_id,
        patch.task_id,
        tuple(operations),
        patch.reason,
        patch.expected_revision,
    )


def _number(value: object) -> float | None:
    try:
        if value is None or isinstance(value, bool) or isinstance(value, str) and not value.strip():
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


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
