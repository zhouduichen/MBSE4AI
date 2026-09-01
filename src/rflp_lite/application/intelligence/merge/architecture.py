"""Architecture block merger."""

from __future__ import annotations

from rflp_lite.application.intelligence.merge.architecture_reconciler import (
    merge_architecture_items,
)
from rflp_lite.application.intelligence.merge.common import (
    MergeContext,
    State,
    merge_block,
)
from rflp_lite.ports.generative_model import GenerationResponse

BLOCK_ID = "architecture"


def merge_architecture(
    state: State,
    result: State,
    response: GenerationResponse | None = None,
) -> State:
    return merge_block(state, result, response, _apply_architecture)


def _apply_architecture(result: State, context: MergeContext) -> State:
    merge_architecture_items(
        result,
        list(context.raw_items),
        context.input_hash,
        context.block_id,
    )
    return result

