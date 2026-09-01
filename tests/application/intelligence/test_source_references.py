from __future__ import annotations

from rflp_lite.application.intelligence.analysis_blocks import (
    build_analysis_blocks,
    build_block_request,
)
from rflp_lite.application.intelligence.block_schemas import schema_for
from rflp_lite.application.intelligence.pack_composition import compose_pack_selection
from rflp_lite.application.intelligence.source_references import (
    allowed_source_region_ids,
    repair_source_region_ids,
)


def test_allowed_source_region_ids_uses_the_current_batch() -> None:
    state = {
        "document_regions": [
            {"id": "region-2", "text": "第二段"},
            {"id": "region-1", "text": "第一段"},
        ],
        "analysis_input_regions": [{"id": "region-2", "text": "第二段"}],
    }

    assert allowed_source_region_ids(state) == ("region-2",)


def test_dynamic_schema_limits_source_region_ids() -> None:
    schema = schema_for("architecture", ("region-306bc6c648e7",))
    item_schema = schema["properties"]["items"]["items"]
    entity_schema = item_schema["oneOf"][0]

    assert entity_schema["properties"]["source_region_ids"]["items"]["enum"] == [
        "region-306bc6c648e7"
    ]


def test_block_prompt_includes_the_allowed_source_region_ids() -> None:
    state = {
        "project_scope": {"workspace": "demo", "input_hash": "input-1"},
        "document_regions": [{"id": "region-1", "text": "系统"}],
    }
    block = build_analysis_blocks(
        state, compose_pack_selection({"base_pack_id": "common-v1"})
    )[0]
    request = build_block_request(
        state, block, compose_pack_selection({"base_pack_id": "common-v1"})
    )

    assert request.user_payload["allowed_source_region_ids"] == ["region-1"]
    assert "region-1" in request.system_prompt


def test_single_allowed_region_repairs_the_known_model_typo() -> None:
    payload = {
        "block_id": "architecture",
        "items": [
            {
                "id": "fn-1",
                "source_region_ids": ["region-306bc6c6c8e7"],
            }
        ],
        "diagnostics": [],
    }

    repaired, audit = repair_source_region_ids(
        payload, ("region-306bc6c648e7",)
    )

    assert repaired["items"][0]["source_region_ids"] == ["region-306bc6c648e7"]
    assert audit == {
        "code": "source_region_repaired",
        "block_id": "architecture",
        "reason": "single_allowed_source_region",
        "changes": [
            {
                "path": "items[0].source_region_ids[0]",
                "original": "region-306bc6c6c8e7",
                "replacement": "region-306bc6c648e7",
            }
        ],
    }
    assert payload["items"][0]["source_region_ids"] == ["region-306bc6c6c8e7"]


def test_single_allowed_region_repairs_missing_source_reference() -> None:
    repaired, audit = repair_source_region_ids(
        {"block_id": "requirements", "items": [{"id": "req-1"}]},
        ("region-1",),
    )

    assert repaired["items"][0]["source_region_ids"] == ["region-1"]
    assert audit is not None
    assert audit["changes"][0]["original"] is None
    assert audit["changes"][0]["replacement"] == ["region-1"]


def test_multiple_allowed_regions_never_fuzzy_match_an_invalid_id() -> None:
    payload = {
        "block_id": "architecture",
        "items": [
            {
                "id": "fn-1",
                "source_region_ids": ["region-306bc6c6c8e7"],
            }
        ],
        "diagnostics": [],
    }

    unchanged, audit = repair_source_region_ids(
        payload, ("region-1", "region-2")
    )

    assert unchanged == payload
    assert audit is not None
    assert audit["code"] == "source_region_repair_required"
    assert audit["reason"] == "multiple_allowed_source_regions"
    assert audit["changes"][0]["replacement"] is None
