"""Merger for the reviewable explicit requirement detail block."""

from __future__ import annotations

from rflp_lite.application.intelligence.merge.common import MergeContext, State, merge_block
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.ports.generative_model import GenerationResponse


def merge_requirement_details(state: State, result, response: GenerationResponse | None = None) -> State:
    return merge_block(state, result, response, _apply)


def _apply(result: State, context: MergeContext) -> State:
    known_requirements = {
        str(item.get("id"))
        for item in result.get("structured_requirements", ())
        if isinstance(item, dict) and item.get("id")
    }
    known_regions = {
        str(item.get("id"))
        for item in result.get("document_regions", ())
        if isinstance(item, dict) and item.get("id")
    }
    attributes = [dict(item) for item in result.get("requirement_attributes", ()) if isinstance(item, dict)]
    constraints = [dict(item) for item in result.get("requirement_constraints", ()) if isinstance(item, dict)]
    for raw in context.raw_items:
        kind = str(raw.get("kind", ""))
        requirement_ids = [str(raw.get("requirement_id", ""))] if kind == "attribute" else [str(item) for item in raw.get("requirement_ids", ())]
        source_ids = [str(item) for item in raw.get("source_region_ids", ())]
        if not requirement_ids or not set(requirement_ids) <= known_requirements:
            raise ContractViolation("requirement_details 引用了未知 requirement_id")
        if not source_ids or not set(source_ids) <= known_regions:
            raise ContractViolation("requirement_details 引用了未知 source_region_id")
        payload = {
            **raw,
            "status": "candidate",
            "producer": "llm",
            "analysis_block_id": context.block_id,
            "analysis_input_hash": context.input_hash,
            "bulk_approvable": False,
        }
        if kind == "attribute":
            attributes = [item for item in attributes if str(item.get("id")) != str(payload["id"])]
            attributes.append(payload)
        elif kind == "constraint":
            constraints = [item for item in constraints if str(item.get("id")) != str(payload["id"])]
            constraints.append(payload)
        else:
            raise ContractViolation("requirement_details kind 无效")
    result["requirement_attributes"] = sorted(attributes, key=lambda item: str(item.get("id", "")))
    result["requirement_constraints"] = sorted(constraints, key=lambda item: str(item.get("id", "")))
    return result


__all__ = ["merge_requirement_details"]
