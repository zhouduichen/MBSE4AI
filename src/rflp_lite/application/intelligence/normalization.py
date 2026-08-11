"""Deterministic candidate deduplication and conflict diagnostics."""

from __future__ import annotations

import json
from typing import Any

from rflp_lite.domain.canonical import canonical_json


def _name(item: dict[str, object]) -> str:
    payload = item.get("payload")
    if not isinstance(payload, dict):
        return ""
    return " ".join(str(payload.get("name", "")).casefold().split())


def _payload_without_name(item: dict[str, object]) -> dict[str, object]:
    payload = item.get("payload")
    if not isinstance(payload, dict):
        return {}
    return {key: value for key, value in payload.items() if key != "name"}


def _append_unique(target: list[Any], values: object) -> None:
    if not isinstance(values, list):
        return
    existing = {canonical_json(item) for item in target}
    for value in values:
        marker = canonical_json(value)
        if marker not in existing:
            target.append(value)
            existing.add(marker)


def normalize_candidate_sets(state: dict[str, object]) -> dict[str, object]:
    """Return a cloned state with deterministic duplicate handling and diagnostics."""

    result = json.loads(canonical_json(state))
    discovery = result.setdefault("discovery", {})
    if not isinstance(discovery, dict):
        raise ValueError("discovery state must be an object")
    groups = discovery.get("candidate_sets", [])
    if not isinstance(groups, list):
        raise ValueError("candidate_sets must be a list")
    all_items: list[dict[str, object]] = []
    for group in sorted(
        (value for value in groups if isinstance(value, dict)),
        key=lambda value: str(value.get("lens_id", "")),
    ):
        items = group.get("items", [])
        if isinstance(items, list):
            all_items.extend(
                value for value in sorted(items, key=lambda item: str(item.get("id", "")))
                if isinstance(value, dict)
            )
    diagnostics = [
        value for value in discovery.get("diagnostics", []) if isinstance(value, dict)
    ]
    merge_suggestions: list[dict[str, str]] = []
    kept: list[dict[str, object]] = []
    exact: dict[tuple[str, str], dict[str, object]] = {}
    by_name: dict[tuple[str, str], dict[str, object]] = {}
    for item in all_items:
        element_type = str(item.get("element_type", ""))
        content_hash = str(item.get("content_hash", ""))
        key = (element_type, content_hash)
        existing = exact.get(key) if content_hash else None
        if existing is not None:
            _append_unique(existing.setdefault("provenance", []), item.get("provenance"))
            _append_unique(existing.setdefault("assumptions", []), item.get("assumptions"))
            diagnostics.append(
                {"code": "duplicate_merged", "left_id": str(existing.get("id", "")), "right_id": str(item.get("id", ""))}
            )
            continue
        if content_hash:
            exact[key] = item
        name_key = (element_type, _name(item))
        named = by_name.get(name_key) if name_key[1] else None
        if named is not None:
            left_payload = _payload_without_name(named)
            right_payload = _payload_without_name(item)
            if left_payload == right_payload:
                merge_suggestions.append(
                    {"left_id": str(named.get("id", "")), "right_id": str(item.get("id", "")), "reason": "normalized-name-match"}
                )
            else:
                diagnostics.append(
                    {"code": "candidate_conflict", "left_id": str(named.get("id", "")), "right_id": str(item.get("id", "")), "element_type": element_type}
                )
        elif name_key[1]:
            by_name[name_key] = item
        kept.append(item)
    normalized_group = {
        "lens_id": "normalized",
        "items": sorted(kept, key=lambda item: (str(item.get("element_type", "")), str(item.get("id", "")))),
    }
    discovery["candidate_sets"] = [normalized_group] if kept else []
    discovery["merge_suggestions"] = sorted(merge_suggestions, key=lambda item: (item["left_id"], item["right_id"]))
    discovery["diagnostics"] = sorted(
        diagnostics,
        key=lambda item: (str(item.get("code", "")), str(item.get("left_id", "")), str(item.get("right_id", ""))),
    )
    discovery["revision"] = int(discovery.get("revision", 0)) + 1
    return result
