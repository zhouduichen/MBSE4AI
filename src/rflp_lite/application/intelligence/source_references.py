"""Deterministic source-region restrictions and repairs for LLM output."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy


def _normalized_ids(values: object) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        return ()
    return tuple(
        sorted(
            {
                str(item.get("id", "")).strip()
                for item in values
                if isinstance(item, Mapping) and str(item.get("id", "")).strip()
            }
        )
    )


def allowed_source_region_ids(state: dict[str, object]) -> tuple[str, ...]:
    """Return the deterministic source IDs available to the current request."""

    selected = state.get("analysis_input_regions")
    if isinstance(selected, (list, tuple)):
        return _normalized_ids(selected)
    return _normalized_ids(state.get("document_regions") or state.get("spans"))


def _change(path: str, original: object, replacement: object) -> dict[str, object]:
    return {"path": path, "original": original, "replacement": replacement}


def repair_source_region_ids(
    payload: dict[str, object], allowed_ids: Iterable[str]
) -> tuple[dict[str, object], dict[str, object] | None]:
    """Repair only deterministic single-source references.

    Multiple allowed regions deliberately return the original payload and an
    audit diagnostic.  The caller can use that diagnostic to request a
    semantic repair without silently choosing a region by string similarity.
    """

    repaired = deepcopy(payload)
    normalized_allowed = tuple(
        sorted({str(value).strip() for value in allowed_ids if str(value).strip()})
    )
    items = repaired.get("items")
    if not isinstance(items, list):
        return repaired, None

    changes: list[dict[str, object]] = []
    for item_index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        path = f"items[{item_index}].source_region_ids"
        raw_values = item.get("source_region_ids")
        if "source_region_ids" not in item:
            if len(normalized_allowed) == 1:
                item["source_region_ids"] = [normalized_allowed[0]]
                changes.append(_change(path, None, [normalized_allowed[0]]))
            elif normalized_allowed:
                changes.append(_change(path, None, None))
            continue

        if isinstance(raw_values, list):
            invalid = [
                (index, value)
                for index, value in enumerate(raw_values)
                if not isinstance(value, str) or value.strip() not in normalized_allowed
            ]
            if not invalid:
                continue
            if len(normalized_allowed) != 1:
                changes.extend(
                    _change(f"{path}[{index}]", value, None)
                    for index, value in invalid
                )
                continue
            replacement = normalized_allowed[0]
            values = [
                value.strip() if isinstance(value, str) and value.strip() in normalized_allowed else replacement
                for value in raw_values
            ]
            item["source_region_ids"] = list(dict.fromkeys(values))
            changes.extend(
                _change(f"{path}[{index}]", value, replacement)
                for index, value in invalid
            )
            continue

        if len(normalized_allowed) == 1:
            item["source_region_ids"] = [normalized_allowed[0]]
            changes.append(_change(path, raw_values, [normalized_allowed[0]]))
        elif normalized_allowed:
            changes.append(_change(path, raw_values, None))

    if not changes:
        return repaired, None

    block_id = str(repaired.get("block_id", ""))
    if len(normalized_allowed) == 1:
        return repaired, {
            "code": "source_region_repaired",
            "block_id": block_id,
            "reason": "single_allowed_source_region",
            "changes": changes,
        }
    return repaired, {
        "code": "source_region_repair_required",
        "block_id": block_id,
        "reason": "multiple_allowed_source_regions",
        "changes": changes,
    }


__all__ = ["allowed_source_region_ids", "repair_source_region_ids"]
