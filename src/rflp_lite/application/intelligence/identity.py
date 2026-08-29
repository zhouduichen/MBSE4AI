"""Stable identity and backward-compatible metadata for analysis entities."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping

from rflp_lite.domain.canonical import canonical_hash, canonical_json


_GROUP_TYPES = {
    "stakeholders": "stakeholder",
    "concerns": "concern",
    "needs": "need",
    "claims": "requirement",
    "structured_requirements": "requirement",
    "scenarios": "scenario",
}
_METADATA_FIELDS = frozenset(
    {
        "field_sources",
        "suggested_changes",
        "suggestion_history",
        "match_keys",
        "identity_hash",
        "source_item_id",
        "analysis_block_id",
        "analysis_input_hash",
        "producer",
        "last_editor",
        "aliases",
    }
)


def normalize_label(value: object) -> str:
    """Return a Unicode-normalized comparison label without punctuation."""

    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return re.sub(r"[\s\-_—–，。；：、,.!！?？:;]+", "", text)


def label_similarity(left: object, right: object) -> float:
    """Calculate a conservative similarity score for human-readable labels."""

    first, second = normalize_label(left), normalize_label(right)
    if not first or not second:
        return 0.0
    if first == second:
        return 1.0
    shorter, longer = sorted((first, second), key=len)
    if len(shorter) >= 4 and shorter in longer:
        return 0.96
    left_pairs = {
        first[index : index + 2] for index in range(max(1, len(first) - 1))
    }
    right_pairs = {
        second[index : index + 2] for index in range(max(1, len(second) - 1))
    }
    return (2.0 * len(left_pairs & right_pairs)) / (
        len(left_pairs) + len(right_pairs)
    )


def entity_match_keys(
    entity_type: str, item: Mapping[str, object]
) -> tuple[str, ...]:
    """Build stable semantic match keys independent of an analysis input hash."""

    aliases = item.get("aliases", ())
    alias_values = aliases if isinstance(aliases, (list, tuple)) else ()
    if entity_type == "stakeholder":
        category = normalize_label(item.get("category", "other")) or "other"
        labels = [item.get("name", ""), *alias_values]
        return tuple(
            sorted(
                {
                    f"stakeholder:{category}:{normalize_label(label)}"
                    for label in labels
                    if normalize_label(label)
                }
            )
        )
    if entity_type == "concern":
        return (
            f"concern:{item.get('stakeholder_id', '')}:"
            f"{normalize_label(item.get('name', ''))}",
        )
    if entity_type == "need":
        return (
            f"need:{item.get('stakeholder_id', '')}:"
            f"{normalize_label(item.get('statement', ''))}",
        )
    if entity_type == "scenario":
        actors = ",".join(
            sorted(
                normalize_label(value)
                for value in item.get("actors", ())
                if normalize_label(value)
            )
        )
        objective = normalize_label(
            item.get("title", item.get("description", ""))
        )
        return (
            f"scenario:{normalize_label(item.get('scenario_type', 'normal'))}:"
            f"{actors}:{objective}",
        )
    statement = normalize_label(
        item.get("statement", item.get("object", item.get("name", "")))
    )
    return (f"{entity_type}:{statement}",) if statement else ()


def ensure_entity_metadata(
    entity_type: str,
    item: Mapping[str, object],
    *,
    editor: str | None = None,
) -> dict[str, object]:
    """Add identity/provenance metadata while preserving existing values and IDs."""

    result = json.loads(canonical_json(dict(item)))
    source = str(
        editor
        or result.get("last_editor")
        or result.get("producer")
        or "rule"
    )
    result.setdefault("revision", 1)
    result.setdefault("last_editor", source)
    result.setdefault("aliases", [])
    result.setdefault(
        "source_requirement_ids", list(result.get("requirement_ids", ()))
    )
    result.setdefault("suggested_changes", [])
    result.setdefault("review_hint", "")
    result.setdefault("match_keys", list(entity_match_keys(entity_type, result)))
    fields = dict(result.get("field_sources") or {})
    for key in result:
        if key not in _METADATA_FIELDS:
            fields.setdefault(key, source)
    result["field_sources"] = fields
    if not result.get("identity_hash"):
        result["identity_hash"] = canonical_hash(
            (entity_type, result["match_keys"])
        )
    if not result.get("id"):
        result["id"] = f"{entity_type}-{str(result['identity_hash'])[:12]}"
    return result


def ensure_workbench_metadata(state: dict[str, object]) -> dict[str, object]:
    """Migrate a Workbench snapshot without changing its existing entity IDs."""

    result = json.loads(canonical_json(state))
    result.setdefault("content_revision", int(result.get("revision", 0)))
    result.setdefault("deletion_registry", [])
    result.setdefault("analysis_summary", {})
    for group, entity_type in _GROUP_TYPES.items():
        result[group] = [
            ensure_entity_metadata(entity_type, item)
            for item in result.get(group, ())
            if isinstance(item, dict)
        ]
    return result


def advance_content_revision(state: dict[str, object]) -> dict[str, object]:
    """Advance the human/source content revision exactly once."""

    result = ensure_workbench_metadata(state)
    result["content_revision"] = int(result.get("content_revision", 0)) + 1
    return result


__all__ = [
    "advance_content_revision",
    "ensure_entity_metadata",
    "ensure_workbench_metadata",
    "entity_match_keys",
    "label_similarity",
    "normalize_label",
]
