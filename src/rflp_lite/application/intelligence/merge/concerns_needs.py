"""Concern and need block merger."""

from __future__ import annotations

from rflp_lite.application.intelligence.merge.common import State

from rflp_lite.application.intelligence.merge.common import (
    MergeContext,
    _source_aliases,
    merge_block,
)
from rflp_lite.application.intelligence.reconciliation import (
    accumulate_summary,
    reconcile_entities,
)
from rflp_lite.ports.generative_model import GenerationResponse

BLOCK_ID = "concerns_needs"


def merge_concerns_needs(
    state: State,
    result: State,
    response: GenerationResponse | None = None,
) -> State:
    return merge_block(state, result, response, _apply_concerns_needs)


def _apply_concerns_needs(
    result: State, context: MergeContext
) -> State:
    aliases = _source_aliases(result)
    mapped_items = []
    for raw in context.raw_items:
        item = dict(raw)
        for field in ("stakeholder_id", "concern_id", "need_id"):
            if field in item:
                item[field] = aliases.get(str(item[field]), str(item[field]))
        mapped_items.append(item)
    concerns = tuple(
        item for item in mapped_items if str(item.get("kind", "concern")) == "concern"
    )
    needs = tuple(item for item in mapped_items if str(item.get("kind", "")) == "need")
    summary = None
    if concerns:
        result, summary = reconcile_entities(
            result,
            "concerns",
            concerns,
            block_id=context.block_id,
            input_hash=context.input_hash,
        )
    if needs:
        aliases = _source_aliases(result)
        needs = tuple(
            {
                **item,
                "stakeholder_id": aliases.get(
                    str(item.get("stakeholder_id", "")),
                    str(item.get("stakeholder_id", "")),
                ),
                "concern_id": aliases.get(
                    str(item.get("concern_id", "")),
                    str(item.get("concern_id", "")),
                ),
            }
            for item in needs
        )
        result, current = reconcile_entities(
            result,
            "needs",
            needs,
            block_id=context.block_id,
            input_hash=context.input_hash,
        )
        summary = current if summary is None else summary.merge(current)
    if summary is not None:
        result["analysis_summary"] = accumulate_summary(result, summary)
    return result
