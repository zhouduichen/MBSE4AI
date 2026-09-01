"""System-scope block merger."""

from __future__ import annotations

from rflp_lite.application.intelligence.merge.common import State

from rflp_lite.application.intelligence.merge.common import (
    MergeContext,
    _label,
    merge_block,
)
from rflp_lite.ports.generative_model import GenerationResponse

BLOCK_ID = "system_scope"


def merge_system_scope(
    state: State,
    result: State,
    response: GenerationResponse | None = None,
) -> State:
    return merge_block(state, result, response, _apply_system_scope)


def _apply_system_scope(
    result: State, context: MergeContext
) -> State:
    if not context.raw_items:
        return result
    first = context.raw_items[0]
    current = (
        result.get("system_context")
        if isinstance(result.get("system_context"), dict)
        else {}
    )
    generated = {
        "name": _label(first, "name", "system_name", "title") or "当前项目",
        "domain": _label(first, "domain", "context") or "待补充领域",
        "mission": _label(first, "mission", "goal", "objective") or "待补充任务",
    }
    updated = dict(current)
    sources = dict(current.get("field_sources") or {})
    suggestions = list(current.get("suggested_changes") or [])
    for field, value in generated.items():
        if updated.get(field) == value:
            continue
        if sources.get(field) in {"user", "rule"}:
            candidate = {
                "field": field,
                "current": updated.get(field),
                "suggested": value,
                "block_id": context.block_id,
                "input_hash": context.input_hash,
            }
            if candidate not in suggestions:
                suggestions.append(candidate)
            continue
        updated[field] = value
        sources[field] = "llm"
    updated.update(
        {
            "producer": current.get("producer", "llm"),
            "analysis_block_id": context.block_id,
            "analysis_input_hash": context.input_hash,
            "field_sources": sources,
            "suggested_changes": suggestions,
        }
    )
    result["system_context"] = updated
    return result
