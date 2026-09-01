"""Shared, persistence-free primitives for block mergers."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from rflp_lite.application.intelligence.reconciliation import accumulate_summary
from rflp_lite.application.intelligence.validated_result import ValidatedBlockResult
from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.ports.generative_model import GenerationResponse


State = dict[str, object]

BLOCK_MAX_ITEMS = {
    "system_scope": 4,
    "stakeholders": 12,
    "concerns_needs": 18,
    "requirements": 16,
    "scenarios": 10,
    "architecture": 18,
}

def input_hash(state: State) -> str:
    scope = state.get("project_scope")
    if isinstance(scope, dict) and str(scope.get("input_hash", "")):
        return str(scope["input_hash"])
    regions = state.get("document_regions") or state.get("spans") or []
    return canonical_hash(regions)

def _clone(value: object) -> object:
    return json.loads(canonical_json(value))


def _label(raw: State, *keys: str) -> str:
    for key in keys:
        value = str(raw.get(key, "")).strip()
        if value:
            return value
    return ""


def _stable_id(state: State, block_id: str, raw: State, label: str) -> str:
    scope = state.get("project_scope")
    workspace = str(scope.get("workspace", "")) if isinstance(scope, dict) else ""
    raw_id = str(raw.get("id", label))
    # Entity identity must survive a later input revision.  The source item ID
    # is preferred when the model supplies one; otherwise the normalized label
    # is stable enough for deterministic reconciliation to resolve it.
    return f"llm-{block_id}-{canonical_hash((workspace, block_id, raw_id, label))[:12]}"


def _remove_block_items(values: object, block_id: str, input_hash: str) -> list[State]:
    return [
        dict(item)
        for item in values
        if isinstance(item, dict)
        and not (
            item.get("producer") == "llm"
            and item.get("analysis_block_id") == block_id
            and item.get("analysis_input_hash") == input_hash
        )
    ] if isinstance(values, list) else []


def _new_item(state: State, block_id: str, raw: State, payload: State, label: str) -> State:
    item = {
        **payload,
        "id": _stable_id(state, block_id, raw, label),
        "status": "accepted",
        "producer": "llm",
        "candidate_type": "inferred",
        "analysis_block_id": block_id,
        "analysis_input_hash": input_hash(state),
        "project_workspace": str((state.get("project_scope") or {}).get("workspace", ""))
        if isinstance(state.get("project_scope"), dict)
        else "",
        "confidence": float(raw.get("confidence", 0.7) or 0.7),
        "assumptions": raw.get("assumptions", []) if isinstance(raw.get("assumptions"), list) else [],
        "rationale": str(raw.get("rationale", "当前项目输入的 LLM 分块推断")),
        "source_region_ids": [str(item.get("id")) for item in raw.get("source_regions", []) if isinstance(item, dict)]
        if isinstance(raw.get("source_regions"), list)
        else [str(item) for item in raw.get("source_region_ids", []) if str(item)],
    }
    source_item_id = str(raw.get("id", "")).strip()
    if source_item_id:
        # Keep the model's identifier so later blocks from the same legacy
        # response can refer to the newly normalized deterministic identifier.
        item["source_item_id"] = source_item_id
    return item


_SINGULAR_RELATIONS = ("stakeholder_id", "concern_id", "need_id", "requirement_id", "source_id", "target_id")
_LIST_RELATIONS = ("requirement_ids", "source_ids", "target_ids")


def _all_ids(state: State) -> set[str]:
    values: set[str] = set()
    for group in ("claims", "structured_requirements", "stakeholders", "concerns", "needs", "scenarios"):
        values.update(
            str(item.get("id"))
            for item in state.get(group, ())
            if isinstance(item, dict) and item.get("id")
        )
    discovery = state.get("discovery")
    architecture = discovery.get("architecture") if isinstance(discovery, dict) else {}
    if isinstance(architecture, dict):
        for key in ("functions", "logical_components", "physical_components", "interfaces", "items"):
            entries = architecture.get(key, ())
            iterable = entries if isinstance(entries, (list, tuple)) else ()
            values.update(
                str(item.get("id"))
                for item in iterable
                if isinstance(item, dict) and item.get("id")
            )
    return values


def _source_aliases(state: State) -> dict[str, str]:
    """Map model-provided ids to the deterministic ids stored in the state."""

    aliases: dict[str, str] = {}
    for group in (
        "claims",
        "structured_requirements",
        "stakeholders",
        "concerns",
        "needs",
        "scenarios",
    ):
        for item in state.get(group, ()):
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("source_item_id", "")).strip()
            item_id = str(item.get("id", "")).strip()
            if source_id and item_id:
                aliases.setdefault(source_id, item_id)
    discovery = state.get("discovery")
    architecture = discovery.get("architecture") if isinstance(discovery, dict) else {}
    if isinstance(architecture, dict):
        for key in ("functions", "logical_components", "physical_components", "interfaces"):
            entries = architecture.get(key, ())
            for item in entries if isinstance(entries, (list, tuple)) else ():
                if not isinstance(item, dict):
                    continue
                source_id = str(item.get("source_item_id", "")).strip()
                item_id = str(item.get("id", "")).strip()
                if source_id and item_id:
                    aliases.setdefault(source_id, item_id)
    return aliases


def _mapped_id(value: object, aliases: dict[str, str], valid_ids: set[str]) -> str:
    raw = str(value or "").strip()
    mapped = aliases.get(raw, raw)
    return mapped if mapped in valid_ids else ""


def _filter_relations(
    item: State, aliases: dict[str, str], valid_ids: set[str]
) -> State:
    result = dict(item)
    for key in _SINGULAR_RELATIONS:
        if key not in result:
            continue
        value = _mapped_id(result[key], aliases, valid_ids)
        if value:
            result[key] = value
        else:
            result.pop(key, None)
    for key in _LIST_RELATIONS:
        if key not in result:
            continue
        values = result[key] if isinstance(result[key], (list, tuple)) else ()
        filtered = sorted(
            {
                value
                for raw in values
                for value in (_mapped_id(raw, aliases, valid_ids),)
                if value
            }
        )
        if filtered:
            result[key] = filtered
        else:
            result.pop(key, None)
    relations = []
    for relation in (result.get("relations", ()) if isinstance(result.get("relations"), list) else ()):
        if not isinstance(relation, dict):
            continue
        source_id = _mapped_id(relation.get("source_id"), aliases, valid_ids)
        target_id = _mapped_id(relation.get("target_id"), aliases, valid_ids)
        if source_id and target_id:
            relations.append(
                {
                    "source_id": source_id,
                    "predicate": str(relation.get("predicate", "relatedTo")),
                    "target_id": target_id,
                }
            )
    if relations:
        result["relations"] = sorted(
            relations,
            key=lambda relation: (
                relation["source_id"], relation["predicate"], relation["target_id"]
            ),
        )
    elif "relations" in result:
        result.pop("relations", None)
    return result


def _architecture_bucket(raw: State) -> str | None:
    kind = str(raw.get("kind", raw.get("type", raw.get("layer", "")))).casefold()
    if kind in {"relation", "relations"}:
        return None
    if "interface" in kind:
        return "interfaces"
    if "logical" in kind or kind in {"l", "component"}:
        return "logical_components"
    if "physical" in kind or kind in {"p", "block"}:
        return "physical_components"
    return "functions"

def items_from_response(response: GenerationResponse) -> list[State]:
    payload = response.payload
    if not isinstance(payload, dict):
        raise ContractViolation("LLM 分析块结果必须是对象")
    values = payload.get("items", [])
    if not values:
        block_id = str(response.lens_id).rsplit(".", 1)[-1]
        legacy_key = {
            "stakeholders": "stakeholders",
            "requirements": "requirements",
            "scenarios": "scenarios",
        }.get(block_id)
        if legacy_key:
            values = payload.get(legacy_key, [])
        elif block_id == "system_scope" and isinstance(payload.get("system"), dict):
            values = [payload["system"]]
        elif block_id == "concerns_needs":
            values = [
                {"concern": item.get("name", ""), **item}
                for item in payload.get("concerns", [])
                if isinstance(item, dict)
            ] + [
                {"statement": item.get("statement", ""), **item}
                for item in payload.get("needs", [])
                if isinstance(item, dict)
            ]
        elif block_id == "architecture" and isinstance(payload.get("architecture"), dict):
            architecture = payload["architecture"]
            values = []
            for key, kind in (
                ("functions", "function"),
                ("logical_components", "logical_component"),
                ("physical_components", "physical_component"),
                ("interfaces", "interface"),
            ):
                for item in (architecture.get(key, []) if isinstance(architecture.get(key), list) else []):
                    if isinstance(item, dict):
                        values.append({**item, "kind": kind})
            for item in (architecture.get("relations", []) if isinstance(architecture.get("relations"), list) else []):
                if isinstance(item, dict):
                    values.append({**item, "kind": "relation"})
    if not isinstance(values, list):
        raise ContractViolation("LLM 分析块 items 必须是数组")
    return [item for item in values if isinstance(item, dict)]

def merge_coverage_decisions(
    state: State,
    decisions: object,
    *,
    block_id: str,
    input_hash: str,
) -> State:
    """Merge model coverage waivers without ever replacing a human decision."""

    if not isinstance(decisions, (list, tuple)):
        return state
    result = state
    current_items = [
        dict(item)
        for item in result.get("coverage_decisions", ())
        if isinstance(item, dict)
    ]
    aliases = _source_aliases(result)
    valid_ids = _all_ids(result)
    for raw in decisions:
        if not isinstance(raw, dict):
            continue
        decision_type = str(raw.get("decision_type", "")).strip()
        key = str(raw.get("key", "")).strip()
        if not decision_type or not key:
            continue
        refs = sorted(
            {
                mapped
                for value in raw.get("source_requirement_ids", ())
                if (mapped := aliases.get(str(value), str(value))) in valid_ids
            }
        )
        if not refs:
            continue
        identity = (decision_type, key, tuple(refs))
        target = next(
            (
                item
                for item in current_items
                if (
                    str(item.get("decision_type", "")),
                    str(item.get("key", "")),
                    tuple(sorted(str(v) for v in item.get("source_requirement_ids", ()) if str(v))),
                )
                == identity
                or str(item.get("id", ""))
                == str(raw.get("id", ""))
            ),
            None,
        )
        suggestion = {
            "status": "not_applicable",
            "rationale": str(raw.get("rationale", "自动分析认为该覆盖维度不适用")).strip(),
            "source_requirement_ids": refs,
        }
        if not suggestion["rationale"]:
            continue
        if target is None:
            target = {
                **suggestion,
                "id": str(
                    raw.get("id")
                    or "coverage-decision-"
                    + canonical_hash(identity)[:12]
                ),
                "decision_type": decision_type,
                "key": key,
                "producer": "llm",
                "last_editor": "llm",
                "revision": 1,
                "analysis_block_id": block_id,
                "analysis_input_hash": input_hash,
                "suggested_changes": [],
                "field_sources": {
                    "status": "llm",
                    "rationale": "llm",
                    "source_requirement_ids": "llm",
                },
            }
            current_items.append(target)
            continue
        sources = dict(target.get("field_sources") or {})
        pending = list(target.get("suggested_changes") or [])
        for field, value in suggestion.items():
            if target.get(field) == value:
                continue
            if sources.get(field) in {"user", "rule"}:
                candidate = {
                    "field": field,
                    "current": target.get(field),
                    "suggested": value,
                    "block_id": block_id,
                    "input_hash": input_hash,
                }
                if candidate not in pending:
                    pending.append(candidate)
                continue
            target[field] = value
            sources[field] = "llm"
        target["suggested_changes"] = pending
        target["field_sources"] = sources
        target["producer"] = target.get("producer", "llm")
        target["analysis_block_id"] = block_id
        target["analysis_input_hash"] = input_hash
    result["coverage_decisions"] = sorted(
        current_items,
        key=lambda item: str(item.get("id", "")),
    )
    return result



@dataclass(frozen=True, slots=True)
class MergeContext:
    block_id: str
    response: GenerationResponse
    payload: State
    input_hash: str
    raw_items: tuple[State, ...]
    valid_ids: frozenset[str]


MergeProcessor = Callable[[State, MergeContext], State]


def prepare_merge(
    state: State,
    result_or_block_id: ValidatedBlockResult | str,
    response: GenerationResponse | None,
) -> tuple[State, MergeContext | None]:
    if isinstance(result_or_block_id, ValidatedBlockResult):
        validated = result_or_block_id
        block_id = validated.block_id
        response = GenerationResponse(
            lens_id=str(validated.provenance.get("lens_id", "")),
            payload={
                "input_hash": validated.input_hash,
                "items": list(validated.dto.items),
                "diagnostics": list(validated.diagnostics),
                "coverage_decisions": list(validated.dto.coverage_decisions),
            },
            input_hash=validated.input_hash,
            output_hash=validated.output_hash,
            repaired=validated.repaired,
            provider_id=str(validated.provenance.get("provider_id", "")),
            model_id=str(validated.provenance.get("model_id", "")),
            template_version=str(validated.provenance.get("template_version", "v1")),
        )
    else:
        block_id = result_or_block_id
        if response is None:
            raise ContractViolation("merge_block_result 需要 ValidatedBlockResult")

    if block_id not in BLOCK_MAX_ITEMS:
        raise ContractViolation(f"未知分析块: {block_id}")
    cloned = _clone(state)
    result = cast(State, cloned)
    payload = response.payload if isinstance(response.payload, dict) else {}
    current_hash = input_hash(result)
    payload_input_hash = str(payload.get("input_hash", "")).strip()
    if payload_input_hash and payload_input_hash != current_hash:
        return result, None
    payload_block_id = str(payload.get("block_id", "")).strip()
    if payload_block_id and payload_block_id != block_id:
        return result, None
    raw_items = tuple(items_from_response(response)[: BLOCK_MAX_ITEMS[block_id]])
    return result, MergeContext(
        block_id=block_id,
        response=response,
        payload=payload,
        input_hash=current_hash,
        raw_items=raw_items,
        valid_ids=frozenset(_all_ids(result)),
    )


def finalize_merge(
    result: State, context: MergeContext
) -> State:
    discovery = dict(result.get("discovery") or {})
    block_results = dict(discovery.get("block_results") or {})
    block_results[context.block_id] = {
        "items": list(context.raw_items),
        "coverage_decisions": context.payload.get("coverage_decisions", []),
        "diagnostics": (
            context.response.payload.get("diagnostics", [])
            if isinstance(context.response.payload, dict)
            else []
        ),
        "output_hash": context.response.output_hash,
        "repaired": context.response.repaired,
        "provenance": {
            "lens_id": context.response.lens_id,
            "input_hash": context.input_hash,
            "provider_id": context.response.provider_id,
            "model_id": context.response.model_id,
            "template_version": context.response.template_version,
        },
    }
    discovery["block_results"] = block_results
    result["discovery"] = discovery
    return result


def merge_block(
    state: State,
    result_or_block_id: ValidatedBlockResult | str,
    response: GenerationResponse | None,
    processor: MergeProcessor,
) -> State:
    result, context = prepare_merge(state, result_or_block_id, response)
    if context is None:
        return result
    result = merge_coverage_decisions(
        result,
        context.payload.get("coverage_decisions", ()),
        block_id=context.block_id,
        input_hash=context.input_hash,
    )
    return finalize_merge(processor(result, context), context)


