"""Requirement block merger."""

from __future__ import annotations

from rflp_lite.application.intelligence.merge.common import State

from rflp_lite.application.intelligence.merge.common import MergeContext, merge_block
from rflp_lite.application.intelligence.reconciliation import (
    accumulate_summary,
    reconcile_entities,
)
from rflp_lite.ports.generative_model import GenerationResponse

BLOCK_ID = "requirements"


def merge_requirements(
    state: State,
    result: State,
    response: GenerationResponse | None = None,
) -> State:
    return merge_block(state, result, response, _apply_requirements)


def _apply_requirements(
    result: State, context: MergeContext
) -> State:
    structured = tuple(
        {
            **item,
            "source_type": item.get("source_type", "inferred"),
        }
        for item in context.raw_items
    )
    result, summary = reconcile_entities(
        result,
        "structured_requirements",
        structured,
        block_id=context.block_id,
        input_hash=context.input_hash,
    )
    claim_items = tuple(
        {
            **item,
            "object": item.get("object", item.get("statement", "")),
            "structured_requirement_id": item.get(
                "structured_requirement_id", item.get("id", "")
            ),
            "span_id": str(
                (item.get("source_region_ids") or ["input"])[0]
            ).replace("region-", "span-", 1),
        }
        for item in context.raw_items
    )
    result, claim_summary = reconcile_entities(
        result,
        "claims",
        claim_items,
        block_id=context.block_id,
        input_hash=context.input_hash,
    )
    result["analysis_summary"] = accumulate_summary(
        result, summary.merge(claim_summary)
    )
    return result
