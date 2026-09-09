"""Layered, bounded ModelGraph context planning."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Protocol

from rflp_lite.domain.entities import Entity, EntityKind
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.methodology.contracts import ContextBundle, TaskSpec
from rflp_lite.methodology.trace_rules import TRACE_RULES


class TokenEstimator(Protocol):
    def estimate(self, value: object) -> int: ...


class HeuristicTokenEstimator:
    """Provider-neutral estimate that treats CJK characters and words fairly."""

    def estimate(self, value: object) -> int:
        text = str(value)
        cjk = len(re.findall(r"[\u3400-\u9fff]", text))
        latin = len(re.findall(r"[A-Za-z0-9_]+", text))
        punctuation = len(text) - cjk - sum(len(item) for item in re.findall(r"[A-Za-z0-9_]+", text))
        return max(1, cjk + math.ceil(latin * 1.3) + math.ceil(max(0, punctuation) / 4)) if text else 0


@dataclass(frozen=True, slots=True)
class PlannedContext:
    entities: tuple[Entity, ...]
    relations: tuple[Relation, ...]
    token_estimate: int
    layers: tuple[tuple[str, tuple[str, ...]], ...] = ()


class ContextPlanner:
    def __init__(self, estimator: TokenEstimator | None = None):
        self.estimator = estimator or HeuristicTokenEstimator()

    def plan(
        self,
        graph: ModelGraph,
        task: TaskSpec,
        *,
        root_entity_ids: tuple[str, ...] = (),
        token_budget: int = 2000,
    ) -> PlannedContext:
        index = graph.entity_index
        allowed = task.context_query.entity_kinds
        p0 = {item for item in root_entity_ids if item in index}
        if not p0:
            p0 = set()
            for kind in sorted(allowed, key=lambda item: item.value):
                first = next((entity for entity in graph.entities if entity.kind is kind), None)
                if first is not None:
                    p0.add(first.id)
        tiers: list[tuple[str, set[str]]] = [("P0", p0)]
        selected = set(p0)
        direct = (
            self._neighbors(graph, selected, allowed)
            | {entity.id for entity in graph.entities if entity.kind in allowed}
        ) - selected
        tiers.append(("P1", direct))
        selected.update(direct)
        trace = self._trace_neighbors(graph, selected, allowed) - selected
        tiers.append(("P2", trace))
        selected.update(trace)
        tiers.extend((("P3", set()), ("P4", set())))
        chosen = set(p0)
        for layer, candidates in tiers[1:]:
            for entity_id in sorted(candidates):
                candidate = chosen | {entity_id}
                if self._estimate(graph, candidate) <= max(0, token_budget) or layer == "P1" and not chosen:
                    chosen.add(entity_id)
        entities = tuple(sorted((index[item] for item in chosen), key=lambda item: item.id))
        relations = tuple(sorted(
            (relation for relation in graph.relations if relation.source_id in chosen and relation.target_id in chosen),
            key=lambda item: item.id,
        ))
        return PlannedContext(
            entities,
            relations,
            self._estimate(graph, chosen, relations),
            tuple((layer, tuple(sorted(ids & chosen))) for layer, ids in tiers),
        )

    def _neighbors(self, graph: ModelGraph, selected: set[str], allowed: frozenset[EntityKind]) -> set[str]:
        index = graph.entity_index
        result: set[str] = set()
        for relation in graph.relations:
            if relation.source_id in selected and relation.target_id in index and index[relation.target_id].kind in allowed:
                result.add(relation.target_id)
            if relation.target_id in selected and relation.source_id in index and index[relation.source_id].kind in allowed:
                result.add(relation.source_id)
        return result

    def _trace_neighbors(self, graph: ModelGraph, selected: set[str], allowed: frozenset[EntityKind]) -> set[str]:
        result: set[str] = set()
        index = graph.entity_index
        for relation in graph.relations:
            if relation.source_id not in selected and relation.target_id not in selected:
                continue
            source = index.get(relation.source_id)
            target = index.get(relation.target_id)
            if source is None or target is None or source.kind not in allowed or target.kind not in allowed:
                continue
            if any(
                rule.source_kind is source.kind and rule.target_kind is target.kind and relation.predicate in rule.allowed_predicates
                for rule in TRACE_RULES
            ):
                result.update((relation.source_id, relation.target_id))
        return result

    def _estimate(self, graph: ModelGraph, entity_ids: set[str], relations: tuple[Relation, ...] | None = None) -> int:
        index = graph.entity_index
        entities = [index[item] for item in sorted(entity_ids) if item in index]
        relation_values = relations or tuple(
            relation for relation in graph.relations if relation.source_id in entity_ids and relation.target_id in entity_ids
        )
        return sum(self.estimator.estimate({"id": item.id, "kind": item.kind.value, "name": item.meta.name, "payload": item.payload}) for item in entities) + sum(
            self.estimator.estimate({"source": item.source_id, "predicate": item.predicate.value, "target": item.target_id})
            for item in relation_values
        )
