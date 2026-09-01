"""Targeted stale propagation for semantic MBSE edits."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ImpactSet:
    source_ids: tuple[str, ...]
    entity_ids: tuple[str, ...]
    relation_ids: tuple[str, ...]


def impact_for_change(state: dict[str, object], changed_ids: set[str]) -> ImpactSet:
    relations = [item for item in tuple(state.get("trace_links", ())) + tuple((state.get("mbse") or {}).get("trace_links", ())) if isinstance(item, dict)]
    frontier = set(str(value) for value in changed_ids); impacted = set(frontier)
    while frontier:
        current = frontier.pop()
        for relation in relations:
            if str(relation.get("source_id")) == current:
                target = str(relation.get("target_id", ""))
                if target and target not in impacted:
                    impacted.add(target); frontier.add(target)
    relation_ids = tuple(sorted(str(item.get("id", "")) for item in relations if str(item.get("source_id")) in impacted or str(item.get("target_id")) in impacted))
    return ImpactSet(tuple(sorted(str(value) for value in changed_ids)), tuple(sorted(impacted - set(changed_ids))), relation_ids)


def mark_impacted_stale(state: dict[str, object], impact: ImpactSet) -> dict[str, object]:
    import json
    result = json.loads(json.dumps(state, ensure_ascii=False))
    impacted = set(impact.entity_ids)
    model = result.get("mbse") or {}
    for collection in ("actors", "use_cases", "activities", "lifelines", "messages"):
        for item in model.get(collection, ()) if isinstance(model, dict) else ():
            if isinstance(item, dict) and str(item.get("id")) in impacted:
                item["status"] = "stale"
    for relation in result.get("trace_links", ()):
        if isinstance(relation, dict) and str(relation.get("id")) in set(impact.relation_ids):
            relation["status"] = "stale"
    result["stale_entities"] = sorted(impacted)
    return result


__all__ = ["ImpactSet", "impact_for_change", "mark_impacted_stale"]
