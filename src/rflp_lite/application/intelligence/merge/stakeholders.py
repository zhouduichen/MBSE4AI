"""Stakeholder block merger."""

from __future__ import annotations

from rflp_lite.application.intelligence.merge.common import State

from rflp_lite.application.intelligence.merge.common import (
    MergeContext,
    merge_block,
)
from rflp_lite.application.intelligence.reconciliation import (
    accumulate_summary,
    reconcile_entities,
)
from rflp_lite.ports.generative_model import GenerationResponse

BLOCK_ID = "stakeholders"


def merge_stakeholders(
    state: State,
    result: State,
    response: GenerationResponse | None = None,
) -> State:
    return merge_block(state, result, response, _apply_stakeholders)


def _apply_stakeholders(
    result: State, context: MergeContext
) -> State:
    result, summary = reconcile_entities(
        result,
        "stakeholders",
        context.raw_items,
        block_id=context.block_id,
        input_hash=context.input_hash,
    )
    result["analysis_summary"] = accumulate_summary(result, summary)
    return result
