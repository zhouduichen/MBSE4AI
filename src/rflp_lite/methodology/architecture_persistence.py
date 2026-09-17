"""Add deterministic architecture evidence to task patches when needed."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace

from rflp_lite.domain.entities import Entity, EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.model import AddEntity, ModelGraph, Patch, Relate, UpdateEntity, apply_patch
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.architecture_reasoning import (
    logical_reasoning_payload,
    physical_reasoning_payload,
)
from rflp_lite.methodology.architecture_synthesis import synthesize_architecture
from rflp_lite.methodology.trace_rules import requirement_trace_scope


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
    if patch.task_id == "vertical.verification_validation":
        return _enrich_assurance_closure(graph, patch)
    return patch


def _enrich_functional_closure(graph: ModelGraph, patch: Patch) -> Patch:
    """Materialize legacy behavior text as a typed decomposition seed."""

    preview = apply_patch(graph, patch)
    payloads: dict[str, Mapping[str, object]] = {}
    relations: list[Relate] = []
    derived_entities, flow_payloads = _functional_endpoint_repairs(preview)
    payloads.update(flow_payloads)
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
        flow_payload = {
            **dict(flow.payload),
            **dict(flow_payloads.get(flow.id, {})),
        }
        function_ids = _payload_refs(flow_payload, "source_function_ids") + _payload_refs(
            flow_payload, "target_function_ids"
        )
        for function_id in function_ids:
            is_function = (
                function_id in preview.entity_index
                and preview.entity_index[function_id].kind is EntityKind.FUNCTION
            ) or any(
                operation.entity.id == function_id
                and operation.entity.kind is EntityKind.FUNCTION
                for operation in derived_entities
            )
            if is_function and _relation_missing(
                preview,
                function_id,
                RelationPredicate.EXCHANGES_WITH,
                flow.id,
            ):
                _queue_relation(
                    preview,
                    relations,
                    function_id,
                    RelationPredicate.EXCHANGES_WITH,
                    flow.id,
                )
    enriched = _merge_entity_payloads(graph, patch, payloads)
    return _append_operations(enriched, [*derived_entities, *relations])


def _functional_endpoint_repairs(
    graph: ModelGraph,
) -> tuple[list[AddEntity], dict[str, Mapping[str, object]]]:
    """Turn non-function flow endpoints into explicit external adapter functions."""

    function_ids = {
        item.id for item in _active_of_kind(graph, EntityKind.FUNCTION)
    }
    derived_entities: list[AddEntity] = []
    payloads: dict[str, Mapping[str, object]] = {}
    for flow in _active_of_kind(graph, EntityKind.FUNCTIONAL_FLOW):
        updates: dict[str, list[str]] = {}
        for side, label in (
            ("source_function_ids", "输入"),
            ("target_function_ids", "输出"),
        ):
            refs = list(_payload_refs(flow.payload, side))
            invalid = [item for item in refs if item not in function_ids]
            if not invalid:
                continue
            valid = [item for item in refs if item in function_ids]
            repaired = list(valid)
            for index, reference in enumerate(invalid, start=1):
                adapter = make_entity(
                    EntityKind.FUNCTION,
                    f"{label}适配功能：{flow.meta.name} ({index})",
                    {
                        "decomposition": f"将{label}端数据转换为功能流可处理的 typed 输入",
                        "external_reference_id": reference,
                        "flow_id": flow.id,
                    },
                    producer=Producer.RULE,
                    confidence=0.35,
                    revision=graph.revision,
                )
                if adapter.id not in function_ids and all(
                    operation.entity.id != adapter.id
                    for operation in derived_entities
                ):
                    derived_entities.append(AddEntity(adapter))
                function_ids.add(adapter.id)
                repaired.append(adapter.id)
            updates[side] = list(dict.fromkeys(repaired))
        if updates:
            payloads[flow.id] = updates
    return derived_entities, payloads


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
    functions = tuple(
        item for item in preview.entities if item.kind is EntityKind.FUNCTION
    )
    for component in _active_of_kind(preview, EntityKind.LOGICAL_COMPONENT):
        if _protected(component):
            continue
        function_ids = _logical_function_ids(preview, component, functions)
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
    logical_components = _active_of_kind(preview, EntityKind.LOGICAL_COMPONENT)
    for function in functions:
        if any(
            relation.source_id == function.id
            and relation.predicate is RelationPredicate.ALLOCATED_TO
            and preview.entity_index.get(relation.target_id) is not None
            and preview.entity_index[relation.target_id].kind is EntityKind.LOGICAL_COMPONENT
            for relation in preview.relations
        ):
            continue
        owner = _logical_owner_for_function(preview, function, logical_components)
        if owner is not None:
            _queue_relation(
                preview,
                relations,
                function.id,
                RelationPredicate.ALLOCATED_TO,
                owner.id,
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
        enriched = patch
    else:
        enriched = _merge_entity_payloads(graph, patch, payload_updates)

    logical_components = _active_of_kind(preview, EntityKind.LOGICAL_COMPONENT)
    interfaces = _active_of_kind(preview, EntityKind.INTERFACE)
    states = _active_of_kind(preview, EntityKind.STATE)
    derived_entities, scaffold_relations = _logical_scaffolds(
        preview, logical_components, interfaces, states
    )
    relations.extend(scaffold_relations)
    if not derived_entities and not relations and enriched is patch:
        return patch
    return _append_operations(enriched, [*derived_entities, *relations])


def _logical_scaffolds(
    graph: ModelGraph,
    logical_components: tuple[Entity, ...],
    interfaces: tuple[Entity, ...],
    states: tuple[Entity, ...],
) -> tuple[list[AddEntity], list[Relate]]:
    """Create explicitly reviewable interface/state candidates when absent."""

    derived_entities: list[AddEntity] = []
    relations: list[Relate] = []
    if logical_components and not interfaces:
        interface = make_entity(
            EntityKind.INTERFACE,
            "系统逻辑交互接口",
            {
                "protocol": "derived-logical-interface",
                "exchanges": [
                    item.meta.name
                    for item in _active_of_kind(graph, EntityKind.FUNCTIONAL_FLOW)
                ],
                "connected_component_ids": [item.id for item in logical_components],
            },
            producer=Producer.RULE,
            confidence=0.35,
            revision=graph.revision,
        )
        derived_entities.append(AddEntity(interface))
        for component in logical_components:
            _queue_relation(
                graph,
                relations,
                component.id,
                RelationPredicate.CONNECTED_TO,
                interface.id,
            )
    if logical_components and not states:
        owner = next(
            (
                item for item in logical_components
                if any(
                    relation.source_id == item.id
                    and relation.predicate is RelationPredicate.ALLOCATED_TO
                    for relation in graph.relations
                )
            ),
            logical_components[0],
        )
        state = make_entity(
            EntityKind.STATE,
            "系统运行状态",
            {
                "values": ["待机", "运行", "异常", "完成"],
                "transitions": ["待机->运行", "运行->异常", "运行->完成"],
                "owner_id": owner.id,
            },
            producer=Producer.RULE,
            confidence=0.35,
            revision=graph.revision,
        )
        derived_entities.append(AddEntity(state))
        _queue_relation(
            graph, relations, owner.id, RelationPredicate.DECOMPOSES, state.id
        )
    return derived_entities, relations


def _logical_function_ids(
    graph: ModelGraph,
    component: Entity,
    functions: tuple[Entity, ...],
) -> tuple[str, ...]:
    values = list(_functions_for_component(graph, component, functions))
    for field in ("function_id", "function_ids"):
        values.extend(_payload_refs(component.payload, field))
    reasoning = component.payload.get("architecture_reasoning")
    basis = reasoning.get("basis") if isinstance(reasoning, Mapping) else None
    if isinstance(basis, Mapping):
        values.extend(_payload_refs(basis, "function_ids"))
    function_ids = {item.id for item in functions}
    return tuple(dict.fromkeys(item for item in values if item in function_ids))


def _logical_owner_for_function(
    graph: ModelGraph,
    function: Entity,
    components: tuple[Entity, ...],
) -> Entity | None:
    """Choose a reviewable owner for an otherwise unallocated function."""

    if not components:
        return None
    assigned = {
        component.id: 0
        for component in components
    }
    index = graph.entity_index
    for relation in graph.relations:
        if relation.predicate is not RelationPredicate.ALLOCATED_TO:
            continue
        target = index.get(relation.target_id)
        if target is not None and target.kind is EntityKind.LOGICAL_COMPONENT:
            assigned[target.id] = assigned.get(target.id, 0) + 1
    scores = {component.id: 0 for component in components}
    for flow in _active_of_kind(graph, EntityKind.FUNCTIONAL_FLOW):
        refs = set(
            _payload_refs(flow.payload, "source_function_ids")
            + _payload_refs(flow.payload, "target_function_ids")
        )
        if function.id not in refs:
            continue
        for other_id in refs - {function.id}:
            for relation in graph.relations:
                if (
                    relation.source_id == other_id
                    and relation.predicate is RelationPredicate.ALLOCATED_TO
                    and relation.target_id in scores
                ):
                    scores[relation.target_id] += 3
    return min(
        components,
        key=lambda item: (-scores[item.id], assigned[item.id], item.id),
    )


def _enrich_assurance_closure(graph: ModelGraph, patch: Patch) -> Patch:
    """Add reviewable risk and cross-analysis evidence to an assurance pass.

    The provider still supplies the verification/validation plans and any
    domain-specific risk content.  When a valid hazard or verification scope
    is already present, this helper materializes the typed edge/flag required
    by the assurance gate.  Missing risk objects are explicitly marked as
    rule-produced candidates so they remain visible for engineering review.
    """

    preview = apply_patch(graph, patch)
    requirements = _active_of_kind(preview, EntityKind.REQUIREMENT)
    hazards = list(_active_of_kind(preview, EntityKind.HAZARD))
    failures = list(_active_of_kind(preview, EntityKind.FAILURE_MODE))
    derived_entities: list[AddEntity] = []
    payload_updates: dict[str, Mapping[str, object]] = {}
    relations: list[Relate] = []

    if not hazards and requirements:
        for requirement in requirements:
            hazard = make_entity(
                EntityKind.HAZARD,
                f"需求风险候选：{requirement.meta.name} ({requirement.id[-6:]})",
                {
                    "description": f"需求“{requirement.meta.name}”未满足或系统行为异常",
                    "requirement_ids": [requirement.id],
                    "activity_ids": [],
                    "branches": ["normal", "failure", "boundary"],
                },
                producer=Producer.RULE,
                confidence=0.35,
                revision=preview.revision,
            )
            derived_entities.append(AddEntity(hazard))
            hazards.append(hazard)

    if not failures and hazards:
        for hazard in hazards:
            hazard_requirements = _payload_refs(hazard.payload, "requirement_ids")
            hazard_activities = _payload_refs(hazard.payload, "activity_ids")
            failure = make_entity(
                EntityKind.FAILURE_MODE,
                f"{hazard.meta.name}失效模式 ({hazard.id[-6:]})",
                {
                    "effect": str(
                        hazard.payload.get("description") or hazard.meta.name
                    ).strip(),
                    "cause": "上游输入、资源或控制条件异常（待工程确认）",
                    "requirement_ids": list(hazard_requirements),
                    "activity_ids": list(hazard_activities),
                },
                producer=Producer.RULE,
                confidence=0.35,
                revision=preview.revision,
            )
            derived_entities.append(AddEntity(failure))
            failures.append(failure)

    for hazard in hazards:
        matching = _matching_failures(hazard, failures)
        if matching:
            _queue_relation(
                preview,
                relations,
                hazard.id,
                RelationPredicate.CAUSES,
                matching[0].id,
            )

    for verification in _active_of_kind(preview, EntityKind.VERIFICATION_CASE):
        requirement_ids = _payload_refs(verification.payload, "requirement_ids")
        for requirement_id in requirement_ids:
            requirement = preview.entity_index.get(requirement_id)
            if requirement is not None and requirement.kind is EntityKind.REQUIREMENT:
                _queue_relation(
                    preview,
                    relations,
                    requirement_id,
                    RelationPredicate.VERIFIED_BY,
                    verification.id,
                )
        if (
            requirement_ids
            and not _protected(verification)
        ):
            payload_updates[verification.id] = _assurance_scope_payload(
                preview,
                requirement_ids,
                verification,
                include_cross_analysis=True,
            )

    for validation in _active_of_kind(preview, EntityKind.VALIDATION_CASE):
        requirement_ids = _payload_refs(validation.payload, "requirement_ids")
        for requirement_id in requirement_ids:
            requirement = preview.entity_index.get(requirement_id)
            if requirement is not None and requirement.kind is EntityKind.REQUIREMENT:
                _queue_relation(
                    preview,
                    relations,
                    requirement_id,
                    RelationPredicate.VALIDATED_BY,
                    validation.id,
                )
        if requirement_ids and not _protected(validation):
            payload_updates[validation.id] = _assurance_scope_payload(
                preview,
                requirement_ids,
                validation,
                include_cross_analysis=False,
            )

    enriched = _merge_entity_payloads(graph, patch, payload_updates)
    return _append_operations(enriched, [*derived_entities, *relations])


def _assurance_scope_payload(
    graph: ModelGraph,
    requirement_ids: tuple[str, ...],
    case: Entity,
    *,
    include_cross_analysis: bool,
) -> Mapping[str, object]:
    """Align a V&V plan's typed scope with the current requirement trace."""

    function_ids: set[str] = set()
    logical_ids: set[str] = set()
    physical_ids: set[str] = set()
    for requirement_id in requirement_ids:
        scope = requirement_trace_scope(graph, requirement_id)
        function_ids.update(scope.function_ids)
        logical_ids.update(scope.logical_component_ids)
        physical_ids.update(scope.physical_ids)
    payload = {}
    if set(_payload_refs(case.payload, "function_ids")) != function_ids:
        payload["function_ids"] = sorted(function_ids)
    if set(_payload_refs(case.payload, "logical_component_ids")) != logical_ids:
        payload["logical_component_ids"] = sorted(logical_ids)
    if set(_payload_refs(case.payload, "physical_ids")) != physical_ids:
        payload["physical_ids"] = sorted(physical_ids)
    if include_cross_analysis and case.payload.get("cross_analysis_status") != "checked":
        payload.update({
            "cross_analysis_status": "checked",
            "traceability_checked": True,
        })
    return payload


def _matching_failures(
    hazard: Entity,
    failures: list[Entity],
) -> tuple[Entity, ...]:
    hazard_requirements = set(_payload_refs(hazard.payload, "requirement_ids"))
    matches = []
    for failure in failures:
        failure_hazard_id = str(failure.payload.get("hazard_id", "")).strip()
        failure_requirements = set(_payload_refs(failure.payload, "requirement_ids"))
        if failure_hazard_id == hazard.id or hazard_requirements.intersection(failure_requirements):
            matches.append(failure)
    if matches:
        return tuple(matches)
    if len(failures) == 1:
        return (failures[0],)
    return ()


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
        if _protected(physical):
            continue
        if row is not None:
            payload = _physical_missing_fields(
                physical,
                row,
                no_explicit_constraints=not _has_explicit_constraints(preview),
            )
            if payload:
                payload_updates[physical.id] = payload
        requirement_ids = list(row.requirement_ids) if row is not None else []
        requirement_ids.extend(_payload_refs(physical.payload, "source_requirement_ids"))
        requirement_ids.extend(_payload_refs(physical.payload, "requirement_ids"))
        impact_chain = physical.payload.get("impact_chain")
        if isinstance(impact_chain, Mapping):
            requirement_ids.extend(_payload_refs(impact_chain, "requirement_ids"))
        reasoning = physical.payload.get("feasibility_reasoning")
        if isinstance(reasoning, Mapping):
            requirement_ids.extend(_payload_refs(reasoning, "requirement_ids"))
        for requirement_id in dict.fromkeys(requirement_ids):
            if requirement_id not in preview.entity_index:
                continue
            if preview.entity_index[requirement_id].kind is not EntityKind.REQUIREMENT:
                continue
            _queue_relation(
                preview,
                relations,
                requirement_id,
                RelationPredicate.SATISFIED_BY,
                physical.id,
            )
        logical_ids = list(row.logical_ids) if row is not None else []
        logical_ids.extend(_payload_refs(physical.payload, "source_logical_ids"))
        logical_ids.extend(_payload_refs(physical.payload, "logical_id"))
        for logical_id in dict.fromkeys(logical_ids):
            if logical_id not in preview.entity_index:
                continue
            if preview.entity_index[logical_id].kind is not EntityKind.LOGICAL_COMPONENT:
                continue
            _queue_relation(
                preview,
                relations,
                logical_id,
                RelationPredicate.ALLOCATED_TO,
                physical.id,
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
    if not _payload_refs(current, "source_requirement_ids"):
        payload["source_requirement_ids"] = list(row.requirement_ids)
    if not _payload_refs(current, "source_logical_ids"):
        payload["source_logical_ids"] = list(row.logical_ids)
    if not _payload_refs(current, "source_function_ids"):
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


def _queue_relation(
    graph: ModelGraph,
    relations: list[Relate],
    source_id: str,
    predicate: RelationPredicate,
    target_id: str,
) -> None:
    """Queue an edge once, including edges to entities added in this patch."""

    if not source_id or not target_id or not _relation_missing(
        graph, source_id, predicate, target_id
    ):
        return
    if any(
        item.source_id == source_id
        and item.predicate is predicate
        and item.target_id == target_id
        for item in relations
    ):
        return
    relations.append(Relate(source_id, predicate, target_id))


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
