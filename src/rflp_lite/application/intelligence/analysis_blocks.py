"""Small, schema-bounded project-analysis requests and deterministic merging."""

from __future__ import annotations

from dataclasses import dataclass

from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.application.intelligence.block_schemas import schema_for
from rflp_lite.application.intelligence.source_references import allowed_source_region_ids
from rflp_lite.application.intelligence.project_snapshot import build_project_snapshot
from rflp_lite.application.intelligence.merge.common import input_hash
from rflp_lite.application.intelligence.validated_result import ValidatedBlockResult
from rflp_lite.ports.generative_model import GenerationRequest, GenerationResponse


@dataclass(frozen=True, slots=True)
class AnalysisBlock:
    id: str
    max_items: int
    max_tokens: int
    response_schema: dict[str, object]


_BLOCK_SPECS = (
    ("system_scope", 4, 500, "system_scope：明确系统边界、任务目标、运行环境和未知前提。"),
    ("stakeholders", 12, 1200, "stakeholders：识别与系统目标、使用、运营、监管、供应和环境有关的利益相关方。"),
    ("concerns_needs", 18, 1400, "concerns_needs：为已识别利益相关方补充关注点和可追溯需要，不生成架构。"),
    ("requirements", 16, 1600, "requirements：把明确目标和需要转成短小、可验证、可追溯的需求。"),
    ("requirement_details", 32, 1800, "requirement_details：补充已识别需求的属性和显式约束；不得生成隐含约束。"),
    ("implicit_constraints", 32, 1800, "implicit_constraints：提出需人工逐条确认的隐含约束，不得自动批准。"),
    ("scenarios", 10, 1400, "scenarios：生成正常、边界、故障、恢复和误操作场景，不生成架构。"),
    ("architecture", 18, 1600, "architecture：基于已接受需求给出功能、逻辑组件、物理组件和接口候选。"),
)
_BLOCK_TASKS = {item[0]: item[3] for item in _BLOCK_SPECS}

def build_analysis_blocks(
    state: dict[str, object], composed_pack: dict[str, object]
) -> tuple[AnalysisBlock, ...]:
    del composed_pack
    source_region_ids = allowed_source_region_ids(state)
    return tuple(
        AnalysisBlock(
            block_id,
            max_items,
            max_tokens,
            schema_for(block_id, source_region_ids),
        )
        for block_id, max_items, max_tokens, _task in _BLOCK_SPECS
    )


def _input_hash(state: dict[str, object]) -> str:
    return input_hash(state)


def _regions(state: dict[str, object]) -> list[dict[str, object]]:
    values = state.get("document_regions") or state.get("spans") or []
    values = [
        {"id": str(item.get("id", "")), "text": str(item.get("text", ""))}
        for item in values
        if isinstance(item, dict) and str(item.get("text", "")).strip()
    ]
    selected = state.get("analysis_input_regions")
    if isinstance(selected, list):
        return [dict(item) for item in selected if isinstance(item, dict)]
    return values


def _accepted_requirements(state: dict[str, object]) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    structured_ids: set[str] = set()
    for group in ("structured_requirements", "claims"):
        for item in (state.get(group, ()) if isinstance(state.get(group), (list, tuple)) else ()):
            if not isinstance(item, dict) or str(item.get("status", "")).casefold() != "accepted":
                continue
            item_id = str(item.get("id", "")).strip()
            linked_id = str(item.get("structured_requirement_id", "")).strip()
            if group == "claims" and linked_id and linked_id in structured_ids:
                continue
            values.append(
                {
                    "id": item_id,
                    "statement": str(item.get("statement", item.get("object", ""))),
                    "subject": str(item.get("subject", "")),
                    "status": "accepted",
                }
            )
            if group == "structured_requirements" and item_id:
                structured_ids.add(item_id)
    return sorted(values, key=lambda item: (str(item.get("id", "")), canonical_json(item)))


def _current_entities_for(block_id: str, state: dict[str, object]) -> object:
    groups = {
        "stakeholders": ("stakeholders",),
        "concerns_needs": ("concerns", "needs"),
        "requirements": ("claims", "structured_requirements"),
        "requirement_details": ("requirement_attributes", "requirement_constraints"),
        "scenarios": ("scenarios",),
        "architecture": ("discovery",),
        "system_scope": ("system_context",),
    }
    selected = groups.get(block_id, ())
    if block_id == "architecture":
        discovery = state.get("discovery")
        return (discovery.get("architecture", {}) if isinstance(discovery, dict) else {})
    if block_id == "system_scope":
        return state.get("system_context") or {}
    return {
        group: list(state.get(group, ()))
        for group in selected
        if isinstance(state.get(group), (list, tuple))
    }


def _current_architecture_for(state: dict[str, object]) -> dict[str, object]:
    discovery = state.get("discovery")
    architecture = discovery.get("architecture") if isinstance(discovery, dict) else {}
    if not isinstance(architecture, dict):
        return {"functions": [], "logical_components": [], "physical_components": [], "interfaces": [], "relations": []}
    return {
        key: [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "requirement_ids": item.get("requirement_ids", item.get("source_requirement_ids", [])),
            }
            for item in architecture.get(key, ())
            if isinstance(item, dict)
        ]
        for key in ("functions", "logical_components", "physical_components", "interfaces", "relations")
    }


def _guidance(block_id: str, pack: dict[str, object]) -> dict[str, object]:
    fields = {
        "stakeholders": ("stakeholder_lenses", "coverage_rules"),
        "concerns_needs": ("stakeholder_lenses", "prompt_fragments"),
        "requirements": ("coverage_rules", "prompt_fragments"),
        "requirement_details": ("coverage_rules", "prompt_fragments"),
        "implicit_constraints": ("scenario_dimensions", "coverage_rules", "prompt_fragments"),
        "scenarios": ("scenario_dimensions", "coverage_rules", "prompt_fragments"),
        "architecture": ("lifecycle_phases", "coverage_rules", "prompt_fragments"),
        "system_scope": ("lifecycle_phases", "scenario_dimensions"),
    }[block_id]
    return {key: pack.get(key, {}) for key in fields if pack.get(key, {}) not in (None, {}, [])}


def build_block_request(
    state: dict[str, object], block: AnalysisBlock, composed_pack: dict[str, object]
) -> GenerationRequest:
    """Build one bounded request without carrying unrelated block instructions."""

    input_hash = _input_hash(state)
    source_region_ids = allowed_source_region_ids(state)
    scope = state.get("project_scope") if isinstance(state.get("project_scope"), dict) else {}
    snapshot = build_project_snapshot(
        state,
        mode=str(state.get("analysis_mode", "incremental")),
        delta_region_ids=tuple(str(value) for value in state.get("delta_region_ids", ()) if str(value)),
    )
    payload = {
        "block_id": block.id,
        "input_hash": input_hash,
        "project_scope": state.get("project_scope", {}),
        "pack_ids": list(composed_pack.get("pack_ids", ())),
        "pack_hashes": composed_pack.get("pack_hashes", {}),
        "limits": {"max_items": block.max_items, "max_tokens": block.max_tokens},
        "task": _BLOCK_TASKS[block.id],
        "input_regions": _regions(state),
        "accepted_requirements": _accepted_requirements(state),
        "pack_guidance": _guidance(block.id, composed_pack),
        "analysis_mode": snapshot["mode"],
        "workspace": snapshot["workspace"] or str(scope.get("workspace", "")),
        "snapshot_revision": snapshot["revision"],
        "snapshot_content_revision": snapshot["content_revision"],
        "delta_region_ids": snapshot["delta_region_ids"],
        "current_entities": _current_entities_for(block.id, state),
        "current_architecture": _current_architecture_for(state),
        "coverage_gaps": state.get("analysis_coverage", {}),
        "deletion_registry": snapshot["deletion_registry"],
        "batch_index": int(state.get("analysis_batch_index", 1) or 1),
        "batch_count": int(state.get("analysis_batch_count", 1) or 1),
        "allowed_source_region_ids": list(source_region_ids),
    }
    source_guidance = (
        "source_region_ids 只能逐字复制以下允许的来源 ID："
        f"{list(source_region_ids)}。不要改写、截断或自行生成 ID。"
        if source_region_ids
        else "当前批次没有可用来源 ID；不要伪造来源 ID。"
    )
    prompt = (
        "你是一个严格的 MBSE 分析块。只完成当前 task，返回 response_schema 对象；"
        "items 最多达到 limits.max_items，内容简短、可追溯，不要解释 JSON。"
        + source_guidance
    )
    return GenerationRequest(
        lens_id=f"project_analysis.{block.id}",
        system_prompt=prompt,
        user_payload=payload,
        response_schema=schema_for(block.id, source_region_ids),
        max_tokens=block.max_tokens,
    )


def merge_block_result(
    state: dict[str, object],
    result_or_block_id: ValidatedBlockResult | str,
    response: GenerationResponse | None = None,
) -> dict[str, object]:
    """Dispatch validated output through the merge registry.

    The registry boundary is persistence-free; this function remains as the
    stable compatibility entry point for existing callers.
    """

    from rflp_lite.application.intelligence.merge.registry import dispatch_merge

    return dispatch_merge(state, result_or_block_id, response)


__all__ = ["AnalysisBlock", "build_analysis_blocks", "build_block_request", "merge_block_result"]
