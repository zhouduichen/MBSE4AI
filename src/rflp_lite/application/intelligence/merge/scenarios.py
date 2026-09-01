"""Scenario block merger."""

from __future__ import annotations

from rflp_lite.application.intelligence.merge.common import State

from rflp_lite.application.intelligence.merge.common import (
    MergeContext,
    _all_ids,
    _filter_relations,
    _source_aliases,
    merge_block,
)
from rflp_lite.application.intelligence.reconciliation import (
    accumulate_summary,
    reconcile_entities,
)
from rflp_lite.ports.generative_model import GenerationResponse

BLOCK_ID = "scenarios"


def merge_scenarios(
    state: State,
    result: State,
    response: GenerationResponse | None = None,
) -> State:
    return merge_block(state, result, response, _apply_scenarios)


def _apply_scenarios(
    result: State, context: MergeContext
) -> State:
    aliases = _source_aliases(result)
    valid_ids = _all_ids(result)
    scenario_items = []
    for raw in context.raw_items:
        item = dict(raw)
        for field in ("requirement_ids", "stakeholder_ids"):
            if field not in item or not isinstance(item[field], list):
                continue
            item[field] = sorted(
                {
                    aliases.get(str(value), str(value))
                    for value in item[field]
                    if aliases.get(str(value), str(value)) in valid_ids
                }
            )
        scenario_items.append(item)
    result, summary = reconcile_entities(
        result,
        "scenarios",
        tuple(scenario_items),
        block_id=context.block_id,
        input_hash=context.input_hash,
    )
    result["analysis_summary"] = accumulate_summary(result, summary)
    return result
