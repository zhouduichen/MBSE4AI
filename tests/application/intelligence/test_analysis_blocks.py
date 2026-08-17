from rflp_lite.application.intelligence.analysis_blocks import (
    build_analysis_blocks,
    build_block_request,
    merge_block_result,
)
from rflp_lite.application.intelligence.pack_composition import compose_pack_selection
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.ports.generative_model import GenerationResponse


def _state():
    return {
        "project_scope": {"workspace": "demo", "input_hash": "input-1"},
        "document_regions": [{"id": "region-1", "text": "系统应支持备份。"}],
        "claims": [],
        "structured_requirements": [],
        "stakeholders": [],
        "concerns": [],
        "needs": [],
        "scenarios": [],
        "discovery": {},
    }


def _pack():
    return compose_pack_selection({"base_pack_id": "common-v1"})


def test_build_blocks_has_bounded_output_contract():
    blocks = build_analysis_blocks(_state(), _pack())
    assert [item.id for item in blocks] == [
        "system_scope", "stakeholders", "concerns_needs",
        "requirements", "scenarios", "architecture",
    ]
    assert [item.max_tokens for item in blocks] == [500, 1200, 1400, 1600, 1400, 1600]
    assert all(item.max_items > 0 and item.max_tokens <= 1600 for item in blocks)


def test_block_request_contains_only_block_scope():
    block = next(item for item in build_analysis_blocks(_state(), _pack()) if item.id == "stakeholders")
    request = build_block_request(_state(), block, _pack())
    assert request.max_tokens == 1200
    assert "stakeholders" in request.user_payload["task"]
    assert "architecture" not in request.user_payload["task"]
    assert request.user_payload["input_hash"] == "input-1"


def test_block_request_contains_accepted_requirements_and_related_guidance_only():
    state = _state()
    state["claims"] = [
        {"id": "accepted-1", "object": "支持备份", "subject": "系统", "status": "accepted"},
        {"id": "rejected-1", "object": "废弃能力", "subject": "系统", "status": "rejected"},
    ]
    pack = _pack()
    block = next(item for item in build_analysis_blocks(state, pack) if item.id == "stakeholders")
    request = build_block_request(state, block, pack)

    assert [item["id"] for item in request.user_payload["accepted_requirements"]] == ["accepted-1"]
    assert set(request.user_payload["pack_guidance"]) == {"stakeholder_lenses", "coverage_rules"}
    assert "architecture" not in request.user_payload["pack_guidance"]


def test_repeated_block_catalog_and_request_calls_are_equal():
    first = build_analysis_blocks(_state(), _pack())
    second = build_analysis_blocks(_state(), _pack())
    assert first == second
    assert build_block_request(_state(), first[2], _pack()) == build_block_request(_state(), second[2], _pack())


def test_merge_is_stable_and_keeps_llm_items_accepted():
    block = next(item for item in build_analysis_blocks(_state(), _pack()) if item.id == "stakeholders")
    payload = {"items": [{"id": "operator", "name": "运维人员", "category": "operator"}], "diagnostics": []}
    response = GenerationResponse(
        "project_analysis.stakeholders",
        payload,
        canonical_hash({}),
        canonical_hash(payload),
        False,
    )
    first = merge_block_result(_state(), block.id, response)
    second = merge_block_result(first, block.id, response)
    assert len(second["stakeholders"]) == 1
    assert second["stakeholders"][0]["status"] == "accepted"
    assert second["stakeholders"][0]["id"] == first["stakeholders"][0]["id"]
    assert second == first


def test_merge_ignores_stale_input_and_foreign_architecture_relations():
    state = _state()
    stale = GenerationResponse(
        "project_analysis.stakeholders",
        {"input_hash": "old-input", "items": [{"id": "old", "name": "旧结果"}], "diagnostics": []},
        canonical_hash({}),
        "stale-output",
        False,
    )
    assert merge_block_result(state, "stakeholders", stale) == state

    response = GenerationResponse(
        "project_analysis.architecture",
        {
            "input_hash": "input-1",
            "items": [
                {
                    "id": "f1",
                    "kind": "function",
                    "name": "备份",
                    "relations": [
                        {"source_id": "f1", "predicate": "traces", "target_id": "missing"},
                    ],
                },
                {"id": "l1", "kind": "logical_component", "name": "备份控制"},
            ],
            "diagnostics": [],
        },
        canonical_hash({}),
        "architecture-output",
        False,
    )
    merged = merge_block_result(state, "architecture", response)
    architecture = merged["discovery"]["architecture"]
    assert len(architecture["functions"]) == 1
    assert len(architecture["logical_components"]) == 1
    assert architecture["relations"] == []
