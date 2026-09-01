"""Review-gated merger for model-proposed implicit constraints."""

from __future__ import annotations

from rflp_lite.application.intelligence.merge.common import MergeContext, State, merge_block
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.ports.generative_model import GenerationResponse


def merge_implicit_constraints(state: State, result, response: GenerationResponse | None = None) -> State:
    return merge_block(state, result, response, _apply)


def _apply(result: State, context: MergeContext) -> State:
    known_requirements = {str(item.get("id")) for item in result.get("structured_requirements", ()) if isinstance(item, dict) and item.get("id")}
    known_regions = {str(item.get("id")) for item in result.get("document_regions", ()) if isinstance(item, dict) and item.get("id")}
    values = [dict(item) for item in result.get("requirement_constraints", ()) if isinstance(item, dict)]
    queue = [dict(item) for item in result.get("review_queue", ()) if isinstance(item, dict)]
    for raw in context.raw_items:
        requirement_ids = tuple(str(value) for value in raw.get("requirement_ids", ()) if str(value))
        source_ids = tuple(str(value) for value in raw.get("source_region_ids", ()) if str(value))
        if not requirement_ids or not set(requirement_ids) <= known_requirements:
            raise ContractViolation("implicit constraint references unknown requirement_id")
        if not source_ids or not set(source_ids) <= known_regions:
            raise ContractViolation("implicit constraint references unknown source_region_id")
        payload = {**raw, "explicitness": "inferred", "status": "candidate", "producer": "llm", "bulk_approvable": False, "analysis_block_id": context.block_id, "analysis_input_hash": context.input_hash}
        values = [item for item in values if str(item.get("id")) != str(payload["id"])]
        values.append(payload)
        queue = [item for item in queue if not (str(item.get("group")) == "requirement_constraints" and str(item.get("item_id")) == str(payload["id"]))]
        queue.append({"group": "requirement_constraints", "item_id": payload["id"], "reason": "implicit_constraint", "requires_confirmation": True, "status": "candidate", "resolved": False})
    result["requirement_constraints"] = sorted(values, key=lambda item: str(item.get("id", "")))
    result["review_queue"] = sorted(queue, key=lambda item: (str(item.get("group", "")), str(item.get("item_id", ""))))
    return result


__all__ = ["merge_implicit_constraints"]
