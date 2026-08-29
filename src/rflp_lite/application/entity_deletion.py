"""Human-only deletion previews, suppression records, and restoration."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping

from rflp_lite.application.intelligence.identity import (
    advance_content_revision,
    ensure_entity_metadata,
)
from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import ContractViolation


_ENTITY_GROUPS = {
    "stakeholder": "stakeholders",
    "requirement": "claims",
    "scenario": "scenarios",
}
_GROUP_ENTITY_TYPES = {
    "stakeholders": "stakeholder",
    "concerns": "concern",
    "needs": "need",
    "claims": "requirement",
    "structured_requirements": "requirement",
    "scenarios": "scenario",
}
_REFERENCE_FIELDS = (
    "stakeholder_id",
    "concern_id",
    "need_id",
    "requirement_id",
    "source_id",
    "target_id",
)
_REFERENCE_LIST_FIELDS = (
    "stakeholder_ids",
    "concern_ids",
    "need_ids",
    "requirement_ids",
    "source_ids",
    "target_ids",
)
_REVIEW_HINT = "原利益相关方已由人工删除，请重新关联"


def _clone(value: dict[str, object]) -> dict[str, object]:
    return json.loads(canonical_json(value))


def _items(state: Mapping[str, object], group: str) -> tuple[dict[str, object], ...]:
    values = state.get(group, ())
    if not isinstance(values, (list, tuple)):
        return ()
    return tuple(item for item in values if isinstance(item, dict))


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return ()
    return tuple(str(item) for item in value if str(item))


def _last_editor(item: Mapping[str, object]) -> str:
    return str(item.get("last_editor") or item.get("producer") or "rule")


def _is_user_edited(item: Mapping[str, object]) -> bool:
    return _last_editor(item) == "user"


def _invalidate_derived_models(state: dict[str, object]) -> None:
    state["rflp"], state["mbse"], state["baseline"] = None, None, None
    state["coverage"], state["analysis_coverage"] = {}, {}
    state["svg"], state["draft_graph"] = "", None
    # RFLP/MBSE traces point at derived element ids which disappear together
    # with the invalidated models.  Keep human/rule evidence where possible,
    # but never leave machine traces dangling into a model that no longer
    # exists; the project-reference validator must remain truthful after a
    # human deletion or restore.
    state["trace_links"] = [
        item
        for item in _items(state, "trace_links")
        if str(item.get("producer", "")) not in {"rflp", "mbse"}
    ]


def _relation_key(item: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        str(item.get("source_id", "")),
        str(item.get("predicate", "")),
        str(item.get("target_id", "")),
    )


def _ordered_union(*values: Iterable[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for collection in values:
        for raw in collection:
            value = str(raw)
            if value and value not in seen:
                seen.add(value)
                result.append(value)
    return result


def preview_entity_deletion(
    state: dict[str, object], entity_type: str, entity_id: str
) -> dict[str, object]:
    """Describe the exact impact of a supported human deletion without mutation."""

    group = _ENTITY_GROUPS.get(entity_type)
    if group is None:
        raise ContractViolation("不支持删除该对象类型")
    target = next(
        (item for item in _items(state, group) if str(item.get("id", "")) == entity_id),
        None,
    )
    if target is None:
        raise ContractViolation("待删除对象不存在")
    target_snapshot = ensure_entity_metadata(entity_type, target)

    dependent_concerns = (
        tuple(
            item
            for item in _items(state, "concerns")
            if str(item.get("stakeholder_id", "")) == entity_id
        )
        if entity_type == "stakeholder"
        else ()
    )
    dependent_needs = (
        tuple(
            item
            for item in _items(state, "needs")
            if str(item.get("stakeholder_id", "")) == entity_id
        )
        if entity_type == "stakeholder"
        else ()
    )
    machine_dependents = tuple(
        item
        for item in (*dependent_concerns, *dependent_needs)
        if not _is_user_edited(item)
    )
    removed_entity_ids = {
        entity_id,
        *(str(item.get("id", "")) for item in machine_dependents),
    }
    removed_entity_ids.discard("")

    target_name = str(target_snapshot.get("name", ""))
    affected_scenarios = tuple(
        item
        for item in _items(state, "scenarios")
        if (
            entity_type == "stakeholder"
            and (
                entity_id in _strings(item.get("stakeholder_ids"))
                or target_name in _strings(item.get("actors"))
            )
        )
        or (
            entity_type == "requirement"
            and entity_id in _strings(item.get("requirement_ids"))
        )
    )
    affected_relations = tuple(
        item
        for item in _items(state, "trace_links")
        if removed_entity_ids.intersection(
            {
                str(item.get("source_id", "")),
                str(item.get("target_id", "")),
            }
        )
    )

    removed_snapshots: dict[str, list[dict[str, object]]] = {
        group: [target_snapshot]
    }
    if entity_type == "stakeholder":
        removed_snapshots["concerns"] = [
            ensure_entity_metadata("concern", item)
            for item in dependent_concerns
            if not _is_user_edited(item)
        ]
        removed_snapshots["needs"] = [
            ensure_entity_metadata("need", item)
            for item in dependent_needs
            if not _is_user_edited(item)
        ]
    if entity_type == "requirement":
        removed_snapshots["structured_requirements"] = [
            ensure_entity_metadata("requirement", item)
            for item in _items(state, "structured_requirements")
            if str(item.get("id", "")) == entity_id
        ]

    recovery = {
        "removed_snapshots": removed_snapshots,
        "scenario_references": [
            {
                "id": str(item.get("id", "")),
                "stakeholder_ids": list(_strings(item.get("stakeholder_ids"))),
                "actors": list(_strings(item.get("actors"))),
                "requirement_ids": list(_strings(item.get("requirement_ids"))),
                "field_sources": dict(item.get("field_sources") or {}),
            }
            for item in affected_scenarios
        ],
        "dependent_references": [
            {
                "group": dependent_group,
                "id": str(item.get("id", "")),
                "stakeholder_id": str(item.get("stakeholder_id", "")),
                "review_hint": str(item.get("review_hint", "")),
            }
            for dependent_group, dependents in (
                ("concerns", dependent_concerns),
                ("needs", dependent_needs),
            )
            for item in dependents
            if _is_user_edited(item)
        ],
        "trace_links": [dict(item) for item in affected_relations],
    }
    affected = {
        "concern_ids": sorted(
            str(item.get("id", ""))
            for item in dependent_concerns
            if str(item.get("id", ""))
        ),
        "need_ids": sorted(
            str(item.get("id", ""))
            for item in dependent_needs
            if str(item.get("id", ""))
        ),
        "scenario_ids": sorted(
            str(item.get("id", ""))
            for item in affected_scenarios
            if str(item.get("id", ""))
        ),
        "relation_ids": sorted(
            str(item.get("id", ""))
            for item in affected_relations
            if str(item.get("id", ""))
        ),
    }
    plan: dict[str, object] = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "target": target_snapshot,
        "affected": affected,
        "recovery": recovery,
        "base_content_revision": int(
            state.get("content_revision", state.get("revision", 0)) or 0
        ),
    }
    return {**plan, "plan_hash": canonical_hash(plan)}


def delete_entity(
    state: dict[str, object],
    entity_type: str,
    entity_id: str,
    plan_hash: str,
) -> dict[str, object]:
    """Apply one explicitly previewed human deletion and register its recovery data."""

    preview = preview_entity_deletion(state, entity_type, entity_id)
    if str(preview["plan_hash"]) != str(plan_hash):
        raise ContractViolation("删除影响已经变化，请重新预览")

    result = _clone(state)
    group = _ENTITY_GROUPS[entity_type]
    result[group] = [
        item
        for item in _items(result, group)
        if str(item.get("id", "")) != entity_id
    ]
    affected = preview["affected"]
    recovery = preview["recovery"]
    target = preview["target"]

    if entity_type == "stakeholder":
        for dependent_group, affected_key in (
            ("concerns", "concern_ids"),
            ("needs", "need_ids"),
        ):
            affected_ids = set(affected[affected_key])
            retained: list[dict[str, object]] = []
            for item in _items(result, dependent_group):
                if str(item.get("id", "")) not in affected_ids:
                    retained.append(item)
                elif _is_user_edited(item):
                    item["stakeholder_id"] = ""
                    item["review_hint"] = _REVIEW_HINT
                    retained.append(item)
            result[dependent_group] = retained
        target_name = str(target.get("name", ""))
        for scenario in _items(result, "scenarios"):
            scenario["stakeholder_ids"] = [
                value
                for value in _strings(scenario.get("stakeholder_ids"))
                if value != entity_id
            ]
            scenario["actors"] = [
                value
                for value in _strings(scenario.get("actors"))
                if value != target_name
            ]
    elif entity_type == "requirement":
        result["structured_requirements"] = [
            item
            for item in _items(result, "structured_requirements")
            if str(item.get("id", "")) != entity_id
        ]
        for scenario in _items(result, "scenarios"):
            scenario["requirement_ids"] = [
                value
                for value in _strings(scenario.get("requirement_ids"))
                if value != entity_id
            ]

    removed_ids = {
        str(snapshot.get("id", ""))
        for snapshots in recovery["removed_snapshots"].values()
        for snapshot in snapshots
        if isinstance(snapshot, dict) and str(snapshot.get("id", ""))
    }
    result["trace_links"] = [
        item
        for item in _items(result, "trace_links")
        if not removed_ids.intersection(
            {
                str(item.get("source_id", "")),
                str(item.get("target_id", "")),
            }
        )
    ]

    registry = [
        item
        for item in _items(result, "deletion_registry")
        if not (
            item.get("entity_type") == entity_type
            and item.get("entity_id") == entity_id
        )
    ]
    registry.append(
        {
            "entity_id": entity_id,
            "entity_type": entity_type,
            "match_keys": list(target.get("match_keys", ())),
            "deleted_revision": int(state.get("revision", 0) or 0),
            "deleted_by": "user",
            "snapshot": dict(target),
            "impact": dict(affected),
            "recovery": dict(recovery),
        }
    )
    result["deletion_registry"] = registry
    _invalidate_derived_models(result)
    return advance_content_revision(result)


def _remap_snapshot_references(
    snapshot: dict[str, object], id_map: Mapping[str, str]
) -> dict[str, object]:
    result = dict(snapshot)
    for field in _REFERENCE_FIELDS:
        value = str(result.get(field, ""))
        if value in id_map:
            result[field] = id_map[value]
    for field in _REFERENCE_LIST_FIELDS:
        if field in result:
            result[field] = [id_map.get(value, value) for value in _strings(result[field])]
    return result


def _merge_restored_snapshot(
    existing: dict[str, object], snapshot: Mapping[str, object]
) -> None:
    existing_id = existing.get("id")
    sources = dict(existing.get("field_sources") or {})
    for field, value in snapshot.items():
        if field == "id" or sources.get(field) == "user":
            continue
        existing[field] = json.loads(canonical_json(value))
    existing["id"] = existing_id


def restore_entity(
    state: dict[str, object], entity_type: str, entity_id: str
) -> dict[str, object]:
    """Restore a registered deletion, merging semantic duplicates safely."""

    group = _ENTITY_GROUPS.get(entity_type)
    if group is None:
        raise ContractViolation("不支持恢复该对象类型")
    result = _clone(state)
    record = next(
        (
            item
            for item in _items(result, "deletion_registry")
            if item.get("entity_type") == entity_type
            and item.get("entity_id") == entity_id
        ),
        None,
    )
    if record is None:
        if any(str(item.get("id", "")) == entity_id for item in _items(result, group)):
            return result
        raise ContractViolation("已删除对象不存在")

    recovery = dict(record.get("recovery") or {})
    raw_removed = recovery.get("removed_snapshots")
    removed_snapshots = (
        raw_removed
        if isinstance(raw_removed, dict)
        else {group: [dict(record.get("snapshot") or {})]}
    )
    id_map: dict[str, str] = {}
    for recovery_group, raw_snapshots in removed_snapshots.items():
        recovery_type = _GROUP_ENTITY_TYPES.get(str(recovery_group))
        if recovery_type is None or not isinstance(raw_snapshots, list):
            continue
        current_items = list(_items(result, str(recovery_group)))
        for raw_snapshot in raw_snapshots:
            if not isinstance(raw_snapshot, dict):
                continue
            remapped = _remap_snapshot_references(raw_snapshot, id_map)
            snapshot = ensure_entity_metadata(recovery_type, remapped)
            snapshot_id = str(snapshot.get("id", ""))
            keys = set(_strings(snapshot.get("match_keys")))
            existing = next(
                (
                    item
                    for item in current_items
                    if str(item.get("id", "")) == snapshot_id
                    or keys.intersection(_strings(item.get("match_keys")))
                ),
                None,
            )
            if existing is None:
                current_items.append(snapshot)
                id_map[snapshot_id] = snapshot_id
            else:
                existing_id = str(existing.get("id", ""))
                _merge_restored_snapshot(existing, snapshot)
                id_map[snapshot_id] = existing_id
        result[str(recovery_group)] = sorted(
            current_items, key=lambda item: str(item.get("id", ""))
        )

    for patch in recovery.get("scenario_references", ()):
        if not isinstance(patch, dict):
            continue
        scenario = next(
            (
                item
                for item in _items(result, "scenarios")
                if item.get("id") == patch.get("id")
            ),
            None,
        )
        if scenario is None:
            continue
        sources = dict(scenario.get("field_sources") or {})
        for field in ("stakeholder_ids", "actors", "requirement_ids"):
            if sources.get(field) == "user":
                continue
            original = (
                id_map.get(value, value)
                for value in _strings(patch.get(field))
            )
            scenario[field] = _ordered_union(original, _strings(scenario.get(field)))

    for patch in recovery.get("dependent_references", ()):
        if not isinstance(patch, dict):
            continue
        dependent_group = str(patch.get("group", ""))
        dependent = next(
            (
                item
                for item in _items(result, dependent_group)
                if item.get("id") == patch.get("id")
            ),
            None,
        )
        if dependent is not None and not dependent.get("stakeholder_id"):
            old_id = str(patch.get("stakeholder_id", ""))
            dependent["stakeholder_id"] = id_map.get(old_id, old_id)
            dependent["review_hint"] = str(patch.get("review_hint", ""))

    existing_relation_keys = {
        _relation_key(item) for item in _items(result, "trace_links")
    }
    trace_links = list(_items(result, "trace_links"))
    for raw_relation in recovery.get("trace_links", ()):
        if not isinstance(raw_relation, dict):
            continue
        relation = _remap_snapshot_references(raw_relation, id_map)
        key = _relation_key(relation)
        if key not in existing_relation_keys:
            trace_links.append(relation)
            existing_relation_keys.add(key)
    result["trace_links"] = trace_links

    result["deletion_registry"] = [
        item
        for item in _items(result, "deletion_registry")
        if not (
            item.get("entity_type") == entity_type
            and item.get("entity_id") == entity_id
        )
    ]
    _invalidate_derived_models(result)
    return advance_content_revision(result)


__all__ = ["delete_entity", "preview_entity_deletion", "restore_entity"]
