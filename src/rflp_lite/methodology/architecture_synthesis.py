"""Deterministic architecture synthesis and feasibility evidence.

This module is deliberately side-effect free.  It turns the current
ModelGraph into reviewable logical partitions and physical feasibility rows;
the runtime may later use the same evidence when a user selects an option.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations

from rflp_lite.domain.entities import EntityKind, EntityStatus
from rflp_lite.domain.model import ModelGraph
from rflp_lite.domain.relations import RelationPredicate


_INACTIVE = frozenset({EntityStatus.REJECTED, EntityStatus.DEPRECATED})
_PHYSICAL_FIELDS = (
    "mass_kg", "power_w", "compute", "memory_mb", "latency_ms",
    "bandwidth_mbps", "cost", "thermal", "reliability", "availability",
    "endurance_h",
)
_LINK_PAYLOAD_KEYS = (
    "source_function_ids", "target_function_ids", "producer_ids",
    "consumer_ids", "source_ids", "target_ids",
)


@dataclass(frozen=True, slots=True)
class LogicalArchitectureCandidate:
    """One explicit function-to-component partition to review."""

    alternative: str
    partitions: tuple[tuple[str, ...], ...]
    component_ids: tuple[str, ...]
    score: float
    cohesion: float
    coupling: float
    cross_component_exchange_count: int
    shared_state_cut_count: int
    dependency_cut_count: int
    rationale: str

    def as_dict(self, names: Mapping[str, str] | None = None) -> Mapping[str, object]:
        labels = names or {}
        return {
            "alternative": self.alternative,
            "component_ids": list(self.component_ids),
            "function_ids": [
                function_id
                for partition in self.partitions
                for function_id in partition
            ],
            "partitions": [list(partition) for partition in self.partitions],
            "partition_names": [
                [labels.get(function_id, function_id) for function_id in partition]
                for partition in self.partitions
            ],
            "score": self.score,
            "cohesion": self.cohesion,
            "coupling": self.coupling,
            "cross_component_exchange_count": self.cross_component_exchange_count,
            "shared_state_cut_count": self.shared_state_cut_count,
            "dependency_cut_count": self.dependency_cut_count,
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class PhysicalFeasibilityRow:
    """Traceable constraint and evidence summary for one physical block."""

    physical_id: str
    requirement_ids: tuple[str, ...]
    propagated_constraints: Mapping[str, object]
    missing_fields: tuple[str, ...]
    conflicts: tuple[Mapping[str, object], ...]
    status: str
    score: float

    def as_dict(self) -> Mapping[str, object]:
        return {
            "physical_id": self.physical_id,
            "requirement_ids": list(self.requirement_ids),
            "propagated_constraints": dict(self.propagated_constraints),
            "missing_fields": list(self.missing_fields),
            "conflicts": [dict(item) for item in self.conflicts],
            "status": self.status,
            "score": self.score,
        }


@dataclass(frozen=True, slots=True)
class ArchitectureSynthesis:
    """The reusable architecture search result exposed by Methodology."""

    logical_candidates: tuple[LogicalArchitectureCandidate, ...] = ()
    physical_rows: tuple[PhysicalFeasibilityRow, ...] = ()

    def as_dict(
        self,
        names: Mapping[str, str] | None = None,
    ) -> Mapping[str, object]:
        return {
            "logical": {
                "candidate_count": len(self.logical_candidates),
                "recommended_alternative": (
                    self.logical_candidates[0].alternative
                    if self.logical_candidates else ""
                ),
                "candidates": [
                    item.as_dict(names) for item in self.logical_candidates
                ],
            },
            "physical": {
                "candidate_count": len(self.physical_rows),
                "rows": [item.as_dict() for item in self.physical_rows],
            },
        }


def synthesize_architecture(
    graph: ModelGraph,
    *,
    active_only: bool = True,
) -> ArchitectureSynthesis:
    """Synthesize logical alternatives and physical feasibility evidence."""

    entities = tuple(
        item for item in graph.entities
        if not active_only or item.meta.status not in _INACTIVE
    )
    functions = tuple(item for item in entities if item.kind is EntityKind.FUNCTION)
    components = tuple(
        item for item in entities if item.kind is EntityKind.LOGICAL_COMPONENT
    )
    physicals = tuple(
        item for item in entities if item.kind is EntityKind.PHYSICAL_BLOCK
    )
    allocations = _relation_targets(graph, entities, RelationPredicate.ALLOCATED_TO)
    logical_candidates = _logical_candidates(graph, functions, components, allocations)
    physical_rows = _physical_rows(graph, entities, physicals, allocations)
    return ArchitectureSynthesis(logical_candidates, physical_rows)


def _logical_candidates(graph, functions, components, allocations):
    if not functions:
        return ()
    function_ids = tuple(item.id for item in functions)
    links = _function_links(graph, functions)
    current = _current_partitions(functions, components, allocations)
    dependency = _connected_partitions(function_ids, links["all"])
    candidates = (
        _score_logical(
            "current_dependency_partition",
            current,
            _component_ids_for_partitions(current, functions, components, allocations),
            links,
            "保留当前分配，同时用功能依赖、功能流和共享状态检查分区质量",
        ),
        _score_logical(
            "dependency_cluster_search",
            dependency,
            (),
            links,
            "按功能流、共享状态和显式依赖形成最小耦合的候选分区",
        ),
        _score_logical(
            "one_component_per_function",
            tuple((item,) for item in function_ids),
            (),
            links,
            "最大化职责隔离，但需要承担更多接口和跨组件交互",
        ),
        _score_logical(
            "shared_coordinator",
            (function_ids,),
            (),
            links,
            "集中共享状态和时序控制，但需要验证单点负载与安全隔离",
        ),
    )
    unique = {}
    for candidate in candidates:
        key = (candidate.alternative, candidate.partitions)
        unique[key] = candidate
    return tuple(
        sorted(
            unique.values(),
            key=lambda item: (-item.score, item.alternative),
        )
    )


def _score_logical(alternative, partitions, component_ids, links, rationale):
    placement = {
        function_id: index
        for index, partition in enumerate(partitions)
        for function_id in partition
    }
    all_links = links["all"]
    cross_links = {
        link for link in all_links
        if placement.get(link[0]) != placement.get(link[1])
    }
    shared_cuts = sum(
        placement.get(first) != placement.get(second)
        for first, second in links["shared_state"]
    )
    dependency_cuts = sum(
        placement.get(first) != placement.get(second)
        for first, second in links["dependency"]
    )
    exchange_crossings = sum(
        len({placement.get(function_id) for function_id in function_ids}) > 1
        for function_ids in links["flows"].values()
    )
    total = len(all_links)
    cohesion = 1.0 if not total else round(1 - len(cross_links) / total, 3)
    coupling = 0.0 if not total else round(len(cross_links) / total, 3)
    sizes = [len(partition) for partition in partitions if partition]
    largest = max(sizes, default=0)
    smallest = min(sizes, default=0)
    balance = 1.0 if not sizes else round(1 - (largest - smallest) / max(largest, 1), 3)
    score = round(
        max(0.0, min(100.0, 55 * cohesion + 25 * balance + 20 - 3 * max(largest - 1, 0))),
        2,
    )
    return LogicalArchitectureCandidate(
        alternative,
        tuple(tuple(partition) for partition in partitions),
        tuple(component_ids),
        score,
        cohesion,
        coupling,
        exchange_crossings,
        shared_cuts,
        dependency_cuts,
        rationale,
    )


def _current_partitions(functions, components, allocations):
    function_ids = {item.id for item in functions}
    groups = []
    assigned = set()
    for component in sorted(components, key=lambda item: item.id):
        members = tuple(
            function_id for function_id in sorted(function_ids)
            if component.id in allocations.get(function_id, ())
            and function_id not in assigned
        )
        if members:
            groups.append(members)
            assigned.update(members)
    groups.extend((function_id,) for function_id in sorted(function_ids - assigned))
    return tuple(groups)


def _component_ids_for_partitions(partitions, functions, components, allocations):
    function_to_components = {
        function.id: tuple(sorted(allocations.get(function.id, ())))
        for function in functions
    }
    result = []
    for partition in partitions:
        choices = [
            component_id
            for function_id in partition
            for component_id in function_to_components.get(function_id, ())
            if any(component.id == component_id for component in components)
        ]
        if choices:
            result.append(sorted(set(choices))[0])
    return tuple(result)


def _connected_partitions(function_ids, links):
    parent = {function_id: function_id for function_id in function_ids}

    def find(item):
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for first, second in links:
        if first not in parent or second not in parent:
            continue
        left, right = find(first), find(second)
        if left != right:
            parent[right] = left
    groups = defaultdict(list)
    for function_id in sorted(function_ids):
        groups[find(function_id)].append(function_id)
    return tuple(tuple(items) for _, items in sorted(groups.items()))


def _function_links(graph, functions):
    function_ids = {item.id for item in functions}
    shared_state = set()
    dependency = set()
    shared_members = defaultdict(list)
    partition_members = defaultdict(list)
    flow_members = defaultdict(set)
    index = {item.id: item for item in graph.entities}
    for function in functions:
        values = function.payload.get("shared_state")
        if isinstance(values, (list, tuple, set)):
            for value in values:
                state_name = str(value).strip()
                if state_name:
                    shared_members[state_name].append(function.id)
        partition = str(
            function.payload.get("logical_partition")
            or function.payload.get("partition_key")
            or ""
        ).strip()
        if partition:
            partition_members[partition].append(function.id)
        dependencies = function.payload.get("dependencies")
        if isinstance(dependencies, (list, tuple, set)):
            dependency.update(
                _pairs(
                    [function.id, *[
                        str(value) for value in dependencies if str(value) in function_ids
                    ]]
                )
            )
    for members in shared_members.values():
        shared_state.update(_pairs(members))
    for members in partition_members.values():
        dependency.update(_pairs(members))
    for relation in graph.relations:
        if relation.source_id not in function_ids:
            continue
        if relation.predicate is RelationPredicate.EXCHANGES_WITH:
            target = index.get(relation.target_id)
            if target is not None and target.kind in {
                EntityKind.FUNCTIONAL_FLOW, EntityKind.INTERFACE,
            }:
                flow_members[relation.target_id].add(relation.source_id)
    for flow_id, flow in index.items():
        if flow.kind not in {EntityKind.FUNCTIONAL_FLOW, EntityKind.INTERFACE}:
            continue
        for key in _LINK_PAYLOAD_KEYS:
            values = flow.payload.get(key)
            if isinstance(values, (list, tuple, set)):
                flow_members[flow_id].update(
                    str(value) for value in values if str(value) in function_ids
                )
    flow_links = {
        flow_id: tuple(sorted(members))
        for flow_id, members in flow_members.items()
        if len(members) >= 2
    }
    flow_pairs = set().union(*(_pairs(members) for members in flow_links.values())) if flow_links else set()
    return {
        "shared_state": shared_state,
        "dependency": dependency,
        "flows": flow_links,
        "all": shared_state | dependency | flow_pairs,
    }


def _physical_rows(graph, entities, physicals, allocations):
    index = {item.id: item for item in entities}
    requirements_by_physical = _requirements_by_physical(graph, index, allocations)
    return tuple(
        _physical_row(physical, requirements_by_physical.get(physical.id, ()))
        for physical in sorted(physicals, key=lambda item: item.id)
    )


def _physical_row(physical, requirements):
    propagated = {}
    conflicts = []
    for requirement in requirements:
        for field, operator, limit in _constraints(requirement):
            propagated[field] = limit if field not in propagated else propagated[field]
            value = _number(physical.payload.get(field))
            if value is None:
                continue
            violates = operator == "max" and value > limit or operator == "min" and value < limit
            if violates:
                conflicts.append({
                    "requirement_id": requirement.id,
                    "field": field,
                    "operator": operator,
                    "limit": limit,
                    "value": value,
                })
    missing = tuple(
        field for field in _PHYSICAL_FIELDS
        if _missing_value(physical.payload.get(field))
    )
    status = (
        "infeasible" if conflicts
        else "needs_measurement" if missing
        else "feasible"
    )
    score = round(max(0.0, 100.0 - 35 * len(conflicts) - 5 * len(missing)), 2)
    return PhysicalFeasibilityRow(
        physical.id,
        tuple(sorted(item.id for item in requirements)),
        dict(sorted(propagated.items())),
        missing,
        tuple(conflicts),
        status,
        score,
    )


def _requirements_by_physical(graph, index, allocations):
    logicals_by_physical = defaultdict(set)
    functions_by_logical = defaultdict(set)
    requirements_by_function = defaultdict(set)
    direct_requirements = defaultdict(set)
    for source_id, targets in allocations.items():
        source = index.get(source_id)
        if source is None:
            continue
        for target_id in targets:
            target = index.get(target_id)
            if target is None:
                continue
            if source.kind is EntityKind.LOGICAL_COMPONENT and target.kind is EntityKind.PHYSICAL_BLOCK:
                logicals_by_physical[target_id].add(source_id)
            if source.kind is EntityKind.FUNCTION and target.kind is EntityKind.LOGICAL_COMPONENT:
                functions_by_logical[target_id].add(source_id)
    for relation in graph.relations:
        if relation.predicate is not RelationPredicate.SATISFIED_BY:
            continue
        source = index.get(relation.source_id)
        target = index.get(relation.target_id)
        if source is not None and target is not None:
            if source.kind is EntityKind.REQUIREMENT and target.kind is EntityKind.FUNCTION:
                requirements_by_function[target.id].add(source.id)
            if source.kind is EntityKind.REQUIREMENT and target.kind is EntityKind.PHYSICAL_BLOCK:
                direct_requirements[target.id].add(source.id)
    result = defaultdict(set)
    for physical_id, logical_ids in logicals_by_physical.items():
        function_ids = {
            function_id for logical_id in logical_ids
            for function_id in functions_by_logical.get(logical_id, ())
        }
        result[physical_id].update(
            requirement_id
            for function_id in function_ids
            for requirement_id in requirements_by_function.get(function_id, ())
        )
        result[physical_id].update(
            direct_requirements.get(physical_id, ())
        )
    for physical_id, requirement_ids in direct_requirements.items():
        result[physical_id].update(requirement_ids)
    return {
        physical_id: tuple(index[requirement_id] for requirement_id in sorted(requirement_ids))
        for physical_id, requirement_ids in result.items()
    }


def _constraints(requirement):
    values = []
    containers = [requirement.payload]
    for key in ("constraints", "limits"):
        nested = requirement.payload.get(key)
        if isinstance(nested, Mapping):
            containers.append(nested)
    for container in containers:
        for key, raw in container.items():
            key_text = str(key)
            if key_text.startswith("max_"):
                number = _number(raw)
                if number is not None:
                    values.append((key_text[4:], "max", number))
            elif key_text.startswith("min_"):
                number = _number(raw)
                if number is not None:
                    values.append((key_text[4:], "min", number))
    unique = {}
    for field, operator, limit in values:
        unique[(field, operator)] = limit
    return tuple((field, operator, limit) for (field, operator), limit in sorted(unique.items()))


def _relation_targets(graph, entities, predicate):
    index = {item.id: item for item in entities}
    result = defaultdict(set)
    for relation in graph.relations:
        if relation.predicate is predicate and relation.source_id in index and relation.target_id in index:
            result[relation.source_id].add(relation.target_id)
    return {source: tuple(sorted(targets)) for source, targets in result.items()}


def _pairs(items: Sequence[str]):
    return set(combinations(sorted(set(items)), 2))


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _missing_value(value):
    return value is None or value == "" or value == "待确认" or value == "unknown"
