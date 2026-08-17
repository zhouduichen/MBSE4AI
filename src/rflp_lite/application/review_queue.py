"""Pure workbench review-queue synchronization helpers."""

from __future__ import annotations

import json

from rflp_lite.domain.canonical import canonical_json


_REVIEW_FIELDS = {
    "stakeholders": "name",
    "concerns": "name",
    "needs": "statement",
    "claims": "object",
    "structured_requirements": "statement",
}
_IMPACT_GROUPS = tuple(_REVIEW_FIELDS)


def _clone(state: dict[str, object]) -> dict[str, object]:
    return json.loads(canonical_json(state))


def _review_entry(
    group: str,
    item: dict[str, object],
    *,
    reason: str,
) -> dict[str, object]:
    field = _REVIEW_FIELDS[group]
    text = str(item.get(field, ""))
    if group == "claims":
        text = " ".join(
            str(item.get(key, ""))
            for key in ("subject", "predicate", "object")
            if str(item.get(key, ""))
        )
    return {
        "group": group,
        "item_id": str(item["id"]),
        "text": text,
        "change_type": "added",
        "reason": reason,
        "requires_confirmation": True,
        "status": str(item.get("status", "candidate")),
        "resolved": False,
    }


def _change_summary(
    items: list[dict[str, object]], review_queue: list[dict[str, object]]
) -> dict[str, int]:
    return {
        "added": sum(item.get("change_type") == "added" for item in items),
        "affected": sum(item.get("change_type") == "affected" for item in items),
        "removed": sum(item.get("change_type") == "removed" for item in items),
        "requires_confirmation": len(review_queue),
    }


def sync_review_queue(state: dict[str, object]) -> dict[str, object]:
    """Keep unresolved candidates and review metadata aligned with the graph."""

    result = _clone(state)
    current: dict[tuple[str, str], dict[str, object]] = {}
    for group in _IMPACT_GROUPS:
        for item in result.get(group, ()):
            current[(group, str(item.get("id", "")))] = item

    queue: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for raw in result.get("review_queue", ()):
        group = str(raw.get("group", ""))
        item_id = str(raw.get("item_id", ""))
        item = current.get((group, item_id))
        if item is None or item.get("status") != "candidate":
            continue
        entry = dict(raw)
        entry["status"] = "candidate"
        entry["resolved"] = False
        queue.append(entry)
        seen.add((group, item_id))

    for group in _IMPACT_GROUPS:
        for item in result.get(group, ()):
            key = (group, str(item.get("id", "")))
            if item.get("status") == "candidate" and key not in seen:
                queue.append(_review_entry(group, item, reason="尚未确认的候选内容"))
                seen.add(key)

    queue.sort(key=lambda item: (str(item.get("group", "")), str(item.get("item_id", ""))))
    result["review_queue"] = queue
    change_set = dict(result.get("change_set") or {})
    impact_items = [dict(item) for item in change_set.get("items", ())]
    pending = {(str(item["group"]), str(item["item_id"])) for item in queue}
    for item in impact_items:
        key = (str(item.get("group", "")), str(item.get("item_id", "")))
        current_item = current.get(key)
        if current_item is not None:
            item["status"] = current_item.get("status", "candidate")
        if item.get("requires_confirmation"):
            item["resolved"] = key not in pending
    change_set["items"] = sorted(
        impact_items,
        key=lambda item: (str(item.get("group", "")), str(item.get("item_id", ""))),
    )
    change_set["summary"] = _change_summary(impact_items, queue)
    result["change_set"] = change_set
    return result
