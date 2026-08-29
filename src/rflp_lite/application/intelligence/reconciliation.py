"""Deterministic, non-destructive reconciliation for automated analysis."""

from __future__ import annotations

import json
from dataclasses import dataclass

from rflp_lite.application.intelligence.identity import (
    ensure_entity_metadata,
    entity_match_keys,
    label_similarity,
)
from rflp_lite.domain.canonical import canonical_json
from rflp_lite.domain.errors import ContractViolation


_GROUP_TYPES = {
    "stakeholders": "stakeholder",
    "concerns": "concern",
    "needs": "need",
    "claims": "requirement",
    "structured_requirements": "requirement",
    "scenarios": "scenario",
    "scenarios": "scenario",
    "architecture_functions": "function",
    "architecture_logical_components": "logical_component",
    "architecture_physical_components": "physical_component",
    "architecture_interfaces": "interface",
}
_ENTITY_OPERATIONS = frozenset(
    {"upsert_entity", "enrich_fields", "propose_change", "flag_for_review"}
)
_RELATION_OPERATIONS = frozenset({"add_relation", "flag_for_review"})
_CONTROL_FIELDS = frozenset(
    {
        "id",
        "target_id",
        "operation",
        "revision",
        "last_editor",
        "field_sources",
        "match_keys",
        "identity_hash",
        "suggested_changes",
        "review_hint",
        "analysis_block_id",
        "analysis_input_hash",
        "source_item_id",
        "producer",
    }
)


@dataclass(frozen=True, slots=True)
class ReconcileSummary:
    added: int = 0
    updated: int = 0
    related: int = 0
    suggested: int = 0
    suppressed: int = 0

    def merge(self, other: "ReconcileSummary") -> "ReconcileSummary":
        return ReconcileSummary(
            *(
                getattr(self, field) + getattr(other, field)
                for field in self.__dataclass_fields__
            )
        )

    def as_dict(self) -> dict[str, int]:
        return {
            field: int(getattr(self, field))
            for field in self.__dataclass_fields__
        }


def accumulate_summary(
    state: dict[str, object], current: ReconcileSummary
) -> dict[str, int]:
    """Add one immutable reconciliation summary to the state's totals."""

    previous = state.get("analysis_summary")
    values = previous if isinstance(previous, dict) else {}
    return {
        field: int(values.get(field, 0)) + int(getattr(current, field))
        for field in current.__dataclass_fields__
    }


def _deleted_keys(state: dict[str, object], entity_type: str) -> set[str]:
    return {
        str(key)
        for entry in state.get("deletion_registry", ())
        if isinstance(entry, dict) and entry.get("entity_type") == entity_type
        for key in entry.get("match_keys", ())
    }


def _suppressed_match_keys(
    state: dict[str, object],
    entity_type: str,
    candidate: dict[str, object],
) -> set[str]:
    candidate_keys = set(entity_match_keys(entity_type, candidate)) | {
        str(key) for key in candidate.get("match_keys", ())
    }
    exact = candidate_keys & _deleted_keys(state, entity_type)
    if exact:
        return exact
    for entry in state.get("deletion_registry", ()):
        if (
            not isinstance(entry, dict)
            or entry.get("entity_type") != entity_type
        ):
            continue
        snapshot = entry.get("snapshot")
        deleted_id = str(entry.get("entity_id", ""))
        if deleted_id and deleted_id in {
            str(candidate.get("id", "")),
            str(candidate.get("source_item_id", "")),
        }:
            return {str(value) for value in entry.get("match_keys", ())}
        if (
            isinstance(snapshot, dict)
            and str(snapshot.get("identity_hash", ""))
            and str(snapshot.get("identity_hash"))
            == str(candidate.get("identity_hash", ""))
        ):
            return {str(value) for value in entry.get("match_keys", ())}
        if not isinstance(snapshot, dict) or not _same_identity_scope(
            entity_type, snapshot, candidate
        ):
            continue
        if (
            label_similarity(
                _primary_label(entity_type, snapshot),
                _primary_label(entity_type, candidate),
            )
            >= 0.92
        ):
            return {str(value) for value in entry.get("match_keys", ())}
    return set()


def _match(
    items: list[dict[str, object]], keys: set[str]
) -> dict[str, object] | None:
    return next(
        (
            item
            for item in items
            if keys.intersection(str(key) for key in item.get("match_keys", ()))
        ),
        None,
    )


def _primary_label(entity_type: str, item: dict[str, object]) -> object:
    if entity_type == "need":
        return item.get("statement", "")
    if entity_type == "scenario":
        return item.get("title", item.get("description", ""))
    return item.get("name", item.get("object", item.get("statement", "")))


def _same_identity_scope(
    entity_type: str,
    left: dict[str, object],
    right: dict[str, object],
) -> bool:
    if entity_type == "stakeholder":
        return left.get("category") == right.get("category")
    if entity_type in {"concern", "need"}:
        return left.get("stakeholder_id") == right.get("stakeholder_id")
    if entity_type == "scenario":
        return left.get("scenario_type", "normal") == right.get(
            "scenario_type", "normal"
        )
    return entity_type in {
        "function",
        "logical_component",
        "physical_component",
        "interface",
    }


def _near_matches(
    entity_type: str,
    items: list[dict[str, object]],
    candidate: dict[str, object],
) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    scored = sorted(
        (
            (
                label_similarity(
                    _primary_label(entity_type, item),
                    _primary_label(entity_type, candidate),
                ),
                item,
            )
            for item in items
            if _same_identity_scope(entity_type, item, candidate)
        ),
        key=lambda pair: (-pair[0], str(pair[1].get("id", ""))),
    )
    possible = [item for score, item in scored if score >= 0.72]
    if not scored or scored[0][0] < 0.92:
        return None, possible
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.08:
        return None, possible
    return scored[0][1], possible


def _append_review_hint(
    state: dict[str, object], hint: dict[str, object]
) -> None:
    hints = list(state.get("analysis_review_hints", ()))
    if hint not in hints:
        hints.append(hint)
    state["analysis_review_hints"] = hints


def reconcile_entities(
    state: dict[str, object],
    group: str,
    incoming: tuple[dict[str, object], ...],
    *,
    block_id: str,
    input_hash: str,
) -> tuple[dict[str, object], ReconcileSummary]:
    """Merge automated entities without deleting or overwriting human fields."""

    if group not in _GROUP_TYPES:
        raise ContractViolation(f"不支持自动对账的实体组: {group}")
    result = json.loads(canonical_json(state))
    entity_type = _GROUP_TYPES[group]
    items = [
        ensure_entity_metadata(entity_type, item)
        for item in result.get(group, ())
        if isinstance(item, dict)
    ]
    summary = ReconcileSummary()
    for raw in incoming:
        if not isinstance(raw, dict):
            raise ContractViolation("自动对账实体必须是对象")
        operation = str(raw.get("operation", "upsert_entity"))
        if operation not in _ENTITY_OPERATIONS:
            raise ContractViolation(f"不允许的实体 operation: {operation}")
        incoming_fields = set(raw)
        candidate_payload = {
            key: value for key, value in raw.items() if key != "operation"
        }
        candidate_payload.setdefault("status", "accepted")
        candidate_payload.setdefault("producer", "llm")
        candidate_payload.setdefault("candidate_type", "inferred")
        candidate = ensure_entity_metadata(
            entity_type, candidate_payload, editor="llm"
        )
        keys = set(entity_match_keys(entity_type, candidate))
        suppressed_keys = _suppressed_match_keys(
            result, entity_type, candidate
        )
        if suppressed_keys:
            _append_review_hint(
                result,
                {
                    "entity_type": entity_type,
                    "match_keys": sorted(suppressed_keys),
                    "operation": operation,
                    "block_id": block_id,
                    "input_hash": input_hash,
                    "message": "模型再次识别到人工删除的对象；保持删除，等待人工恢复。",
                },
            )
            summary = summary.merge(ReconcileSummary(suppressed=1))
            continue

        target_id = str(raw.get("target_id", ""))
        current = next(
            (
                item
                for item in items
                if target_id and item.get("id") == target_id
            ),
            None,
        ) or _match(items, keys)
        possible_duplicates: list[dict[str, object]] = []
        if current is None:
            current, possible_duplicates = _near_matches(
                entity_type, items, candidate
            )
        if current is None:
            if operation != "upsert_entity":
                if not target_id and not keys:
                    raise ContractViolation(
                        f"{operation} 需要 target_id 或可解析的实体匹配键"
                    )
                _append_review_hint(
                    result,
                    {
                        "entity_type": entity_type,
                        "target_id": target_id,
                        "operation": operation,
                        "block_id": block_id,
                        "input_hash": input_hash,
                        "message": str(
                            candidate.get("review_hint")
                            or "未找到建议对应的当前对象"
                        ),
                    },
                )
                summary = summary.merge(ReconcileSummary(suggested=1))
                continue
            source_item_id = str(candidate.get("id", ""))
            candidate["source_item_id"] = source_item_id
            candidate["id"] = (
                f"{entity_type}-{str(candidate['identity_hash'])[:12]}"
            )
            candidate["producer"] = "llm"
            candidate["analysis_block_id"] = block_id
            candidate["analysis_input_hash"] = input_hash
            if possible_duplicates:
                candidate["possible_duplicate_ids"] = sorted(
                    str(item.get("id", "")) for item in possible_duplicates
                )
                candidate["review_hint"] = (
                    "名称相近但无法唯一确认，请人工核对是否重复。"
                )
            items.append(candidate)
            summary = summary.merge(ReconcileSummary(added=1))
            continue

        changed = False
        suggestions = list(current.get("suggested_changes", ()))
        sources = dict(current.get("field_sources") or {})
        if operation == "flag_for_review":
            hint = str(
                candidate.get("review_hint")
                or "模型标记此对象需要人工复核"
            ).strip()
            if hint and current.get("review_hint") != hint:
                current["review_hint"] = hint
                current["revision"] = int(current.get("revision", 1)) + 1
                summary = summary.merge(ReconcileSummary(updated=1))
            continue
        for field, value in candidate.items():
            # Defaults used to make a candidate schema-complete are not
            # proposed as changes when the model omitted that field.
            if field not in incoming_fields:
                continue
            if field in _CONTROL_FIELDS or value in (None, "", [], {}):
                continue
            if current.get(field) == value:
                continue
            if operation == "propose_change" or sources.get(field) in {
                "user",
                "rule",
            }:
                suggestion = {
                    "field": field,
                    "current": current.get(field),
                    "suggested": value,
                    "block_id": block_id,
                    "input_hash": input_hash,
                }
                if suggestion not in suggestions:
                    suggestions.append(suggestion)
                    summary = summary.merge(ReconcileSummary(suggested=1))
                continue
            current[field] = value
            sources[field] = "llm"
            changed = True
        current["field_sources"] = sources
        current["suggested_changes"] = suggestions
        current["match_keys"] = sorted(
            set(current.get("match_keys", ())) | keys
        )
        if changed:
            current["revision"] = int(current.get("revision", 1)) + 1
            current["last_editor"] = "llm"
            summary = summary.merge(ReconcileSummary(updated=1))
    result[group] = sorted(items, key=lambda item: str(item.get("id", "")))
    return result, summary


def _relation_match_key(item: dict[str, object]) -> str:
    source_id = str(item.get("source_id", "")).strip()
    predicate = str(item.get("predicate", "")).strip()
    target_id = str(item.get("target_id", "")).strip()
    if not source_id or not predicate or not target_id:
        return ""
    return f"relation:{source_id}:{predicate}:{target_id}"


def _relation_metadata(
    item: dict[str, object], *, editor: str | None = None
) -> dict[str, object]:
    value = dict(item)
    match_key = _relation_match_key(value)
    if match_key:
        value.setdefault("match_keys", [match_key])
    return ensure_entity_metadata("relation", value, editor=editor)


def _valid_relation_endpoints(state: dict[str, object]) -> set[str]:
    valid = {
        str(value)
        for value in state.get("valid_entity_ids", ())
        if str(value)
    }
    for group in _GROUP_TYPES:
        valid.update(
            str(item.get("id", ""))
            for item in state.get(group, ())
            if isinstance(item, dict) and item.get("id")
        )
    return valid


def reconcile_relations(
    state: dict[str, object],
    incoming: tuple[dict[str, object], ...],
    *,
    block_id: str,
    input_hash: str,
) -> tuple[dict[str, object], ReconcileSummary]:
    """Add relations idempotently; automated reconciliation never removes one."""

    result = json.loads(canonical_json(state))
    relations = [
        _relation_metadata(item)
        for item in result.get("trace_links", ())
        if isinstance(item, dict)
    ]
    valid_ids = _valid_relation_endpoints(result)
    summary = ReconcileSummary()
    for raw in incoming:
        if not isinstance(raw, dict):
            raise ContractViolation("自动对账关系必须是对象")
        operation = str(raw.get("operation", "add_relation"))
        if operation not in _RELATION_OPERATIONS:
            raise ContractViolation(f"不允许的关系 operation: {operation}")

        relation_id = str(raw.get("id", "")).strip()
        key = _relation_match_key(raw)
        current = next(
            (
                item
                for item in relations
                if relation_id and str(item.get("id", "")) == relation_id
            ),
            None,
        )
        if current is None and key:
            current = next(
                (
                    item
                    for item in relations
                    if _relation_match_key(item) == key
                ),
                None,
            )

        if operation == "flag_for_review":
            if current is None:
                raise ContractViolation(
                    "flag_for_review 需要已存在的 relation id 或稳定关系键"
                )
            hint = str(raw.get("review_hint", "模型标记此关系需要人工复核")).strip()
            if hint and current.get("review_hint") != hint:
                current["review_hint"] = hint
                current["revision"] = int(current.get("revision", 1)) + 1
                current["last_editor"] = "llm"
                summary = summary.merge(ReconcileSummary(suggested=1))
            continue

        if not key:
            raise ContractViolation(
                "add_relation 需要 source_id、predicate 和 target_id endpoint"
            )
        source_id = str(raw.get("source_id", ""))
        target_id = str(raw.get("target_id", ""))
        if source_id not in valid_ids or target_id not in valid_ids:
            raise ContractViolation("关系 endpoint 不存在于当前工作台")
        if current is not None:
            continue

        candidate = _relation_metadata(
            {key: value for key, value in raw.items() if key != "operation"},
            editor="llm",
        )
        suppressed_keys = _suppressed_match_keys(result, "relation", candidate)
        if suppressed_keys:
            _append_review_hint(
                result,
                {
                    "entity_type": "relation",
                    "match_keys": sorted(suppressed_keys),
                    "operation": operation,
                    "block_id": block_id,
                    "input_hash": input_hash,
                    "message": "模型再次识别到人工删除的关系；保持删除，等待人工恢复。",
                },
            )
            summary = summary.merge(ReconcileSummary(suppressed=1))
            continue

        source_item_id = str(candidate.get("id", ""))
        candidate["source_item_id"] = source_item_id
        candidate["id"] = f"relation-{str(candidate['identity_hash'])[:12]}"
        candidate["producer"] = "llm"
        candidate["analysis_block_id"] = block_id
        candidate["analysis_input_hash"] = input_hash
        relations.append(candidate)
        summary = summary.merge(ReconcileSummary(related=1))

    result["trace_links"] = sorted(
        relations,
        key=lambda item: (
            str(item.get("source_id", "")),
            str(item.get("predicate", "")),
            str(item.get("target_id", "")),
            str(item.get("id", "")),
        ),
    )
    return result, summary


__all__ = [
    "ReconcileSummary",
    "accumulate_summary",
    "reconcile_entities",
    "reconcile_relations",
]
