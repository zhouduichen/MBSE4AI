"""Deterministic, typed change-impact planning for ModelGraph iterations."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from rflp_lite.domain.entities import EntityKind, EntityStatus
from rflp_lite.domain.errors import NotFoundError
from rflp_lite.domain.model import ModelGraph
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.vertical_generation import (
    vertical_stage_index_for_kind,
    vertical_stage_specs,
)


_INACTIVE = frozenset({EntityStatus.REJECTED, EntityStatus.DEPRECATED})
_IMPACT_STAGE_ORDER = ("requirements", "functional", "logical", "physical", "assurance")
_VERTICAL_STAGE_ORDER = tuple(item.stage.value for item in vertical_stage_specs())
_IMPACTABLE_PREDICATES = frozenset(RelationPredicate)
TASK_ORDER = (
    "system_requirement_derivation",
    "function_identification",
    "functional_decomposition",
    "functional_interaction",
    "logical_analysis",
    "dependency_clustering",
    "architecture_evaluation",
    "physical_candidates",
    "allocation_tradeoff",
    "constraint_propagation",
    "feasibility_selection",
    "reverse_feasibility",
    "verification_validation",
    "global_cross_analysis",
)
_TASKS_BY_KIND = {
    EntityKind.CONCERN: ("stakeholder_analysis", "system_requirement_derivation"),
    EntityKind.LIFECYCLE_TRANSITION: ("lifecycle_analysis", "operational_scenario"),
    EntityKind.REQUIREMENT: (
        "system_requirement_derivation",
        "function_identification",
        "logical_analysis",
        "physical_candidates",
        "verification_validation",
    ),
    EntityKind.FUNCTION: (
        "functional_decomposition",
        "functional_interaction",
        "logical_analysis",
        "physical_candidates",
        "verification_validation",
    ),
    EntityKind.LOGICAL_COMPONENT: (
        "logical_analysis",
        "dependency_clustering",
        "architecture_evaluation",
        "physical_candidates",
        "verification_validation",
    ),
    EntityKind.STATE: (
        "interface_sequence_state",
        "logical_analysis",
        "verification_validation",
    ),
    EntityKind.PHYSICAL_BLOCK: (
        "physical_candidates",
        "constraint_propagation",
        "feasibility_selection",
        "verification_validation",
    ),
    EntityKind.VERIFICATION_CASE: ("verification_validation", "global_cross_analysis"),
    EntityKind.VALIDATION_CASE: ("verification_validation", "global_cross_analysis"),
    EntityKind.HAZARD: (
        "fmea_stpa_hazard",
        "verification_validation",
        "global_cross_analysis",
    ),
    EntityKind.FAILURE_MODE: (
        "fmea_stpa_hazard",
        "reverse_feasibility",
        "global_cross_analysis",
    ),
}


@dataclass(frozen=True, slots=True)
class ImpactPath:
    """One bounded graph path explaining why an entity is affected."""

    entity_ids: tuple[str, ...]
    predicates: tuple[str, ...] = ()
    directions: tuple[str, ...] = ()

    def as_dict(self) -> Mapping[str, object]:
        return {
            "entity_ids": list(self.entity_ids),
            "predicates": list(self.predicates),
            "directions": list(self.directions),
        }


@dataclass(frozen=True, slots=True)
class ImpactPlan:
    """Revision-bound impact facts consumed by review and generation flows."""

    project_id: str
    revision: int
    snapshot_hash: str
    trigger_entity_ids: tuple[str, ...]
    trigger_kinds: tuple[str, ...]
    impacted_entity_ids: tuple[str, ...]
    impacted_stages: tuple[str, ...]
    selected_stages: tuple[str, ...]
    recommended_tasks: tuple[str, ...]
    verification_case_ids: tuple[str, ...]
    validation_case_ids: tuple[str, ...]
    impact_paths: tuple[ImpactPath, ...]
    status: str
    reason: str

    def as_dict(self) -> Mapping[str, object]:
        return {
            "project_id": self.project_id,
            "revision": self.revision,
            "snapshot_hash": self.snapshot_hash,
            "trigger_entity_ids": list(self.trigger_entity_ids),
            "trigger_kinds": list(self.trigger_kinds),
            "impacted_entity_ids": list(self.impacted_entity_ids),
            "impacted_stages": list(self.impacted_stages),
            "selected_stages": list(self.selected_stages),
            "recommended_tasks": list(self.recommended_tasks),
            "verification_case_ids": list(self.verification_case_ids),
            "validation_case_ids": list(self.validation_case_ids),
            "impact_paths": [item.as_dict() for item in self.impact_paths],
            "status": self.status,
            "reason": self.reason,
        }


class TypedImpactPlanner:
    """Build a bounded impact closure without mutating or calling a model."""

    def plan(
        self,
        graph: ModelGraph,
        changed_entity_ids: Sequence[str],
        *,
        max_entities: int = 96,
        max_paths: int = 24,
    ) -> ImpactPlan:
        index = graph.entity_index
        trigger_ids = tuple(dict.fromkeys(str(item).strip() for item in changed_entity_ids if str(item).strip()))
        missing = tuple(item for item in trigger_ids if item not in index)
        if missing:
            raise NotFoundError(f"impact entity not found: {missing[0]}")
        if not trigger_ids:
            raise NotFoundError("impact requires at least one entity")
        entity_limit = max(len(trigger_ids), int(max_entities))
        path_limit = max(0, int(max_paths))
        adjacency = self._adjacency(graph, index)
        visited = set(trigger_ids)
        paths: list[ImpactPath] = []
        queue: deque[tuple[str, ImpactPath]] = deque(
            (entity_id, ImpactPath((entity_id,)))
            for entity_id in sorted(trigger_ids)
        )
        while queue:
            entity_id, path = queue.popleft()
            if len(paths) < path_limit:
                paths.append(path)
            for neighbor, predicate, direction in adjacency.get(entity_id, ()):
                if neighbor in visited or len(visited) >= entity_limit:
                    continue
                visited.add(neighbor)
                queue.append(
                    (
                        neighbor,
                        ImpactPath(
                            (*path.entity_ids, neighbor),
                            (*path.predicates, predicate.value),
                            (*path.directions, direction),
                        ),
                    )
                )

        impacted_ids = tuple(sorted(visited))
        impacted_stages = tuple(
            stage for stage in _IMPACT_STAGE_ORDER
            if any(
                _stage_for_kind(index[entity_id].kind) == stage
                for entity_id in impacted_ids
            )
        )
        earliest_stage = min(
            _stage_for_kind(index[entity_id].kind)
            for entity_id in trigger_ids
        )
        earliest_index = _IMPACT_STAGE_ORDER.index(earliest_stage)
        selected_stages = _VERTICAL_STAGE_ORDER[earliest_index:]
        task_set = {
            task
            for entity_id in impacted_ids
            for task in _TASKS_BY_KIND.get(index[entity_id].kind, ())
        }
        recommended_tasks = tuple(task for task in TASK_ORDER if task in task_set)
        verification_ids = tuple(
            entity_id for entity_id in impacted_ids
            if index[entity_id].kind is EntityKind.VERIFICATION_CASE
        )
        validation_ids = tuple(
            entity_id for entity_id in impacted_ids
            if index[entity_id].kind is EntityKind.VALIDATION_CASE
        )
        downstream_count = len(visited - set(trigger_ids))
        status = "impacted" if downstream_count else "no_downstream_work"
        reason = (
            f"已从 {', '.join(trigger_ids)} 沿 typed ModelGraph 关系发现 "
            f"{len(visited)} 个受影响实体；建议从 {selected_stages[0]} 开始重建。"
            if downstream_count
            else f"实体 {', '.join(trigger_ids)} 没有可传播的下游影响。"
        )
        return ImpactPlan(
            graph.project_id,
            graph.revision,
            graph.snapshot_hash,
            tuple(sorted(trigger_ids)),
            tuple(index[item].kind.value for item in sorted(trigger_ids)),
            impacted_ids,
            impacted_stages,
            selected_stages,
            recommended_tasks,
            verification_ids,
            validation_ids,
            tuple(paths),
            status,
            reason,
        )

    @staticmethod
    def _adjacency(graph, index):
        adjacency: dict[str, list[tuple[str, RelationPredicate, str]]] = {}
        for relation in graph.relations:
            if relation.predicate not in _IMPACTABLE_PREDICATES:
                continue
            source = index.get(relation.source_id)
            target = index.get(relation.target_id)
            if source is None or target is None:
                continue
            if source.meta.status in _INACTIVE or target.meta.status in _INACTIVE:
                continue
            adjacency.setdefault(relation.source_id, []).append(
                (relation.target_id, relation.predicate, "downstream")
            )
            adjacency.setdefault(relation.target_id, []).append(
                (relation.source_id, relation.predicate, "upstream")
            )
        for values in adjacency.values():
            values.sort(key=lambda item: (item[0], item[1].value, item[2]))
        return adjacency


def _stage_for_kind(kind: EntityKind) -> str:
    return _IMPACT_STAGE_ORDER[vertical_stage_index_for_kind(kind)]


__all__ = ["ImpactPath", "ImpactPlan", "TASK_ORDER", "TypedImpactPlanner"]
