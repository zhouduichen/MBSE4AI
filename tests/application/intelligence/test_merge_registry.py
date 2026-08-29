from __future__ import annotations

from rflp_lite.application.intelligence.analysis_blocks import merge_block_result
from rflp_lite.application.intelligence.merge.registry import MERGERS
from rflp_lite.application.intelligence.validated_result import validate_and_build_result
from rflp_lite.ports.generative_model import GenerationResponse


def test_merge_registry_covers_all_blocks_and_does_not_persist() -> None:
    assert set(MERGERS) == {
        "system_scope",
        "stakeholders",
        "concerns_needs",
        "requirements",
        "scenarios",
        "architecture",
    }
    state = {
        "project_scope": {"workspace": "demo", "input_hash": "input-1"},
        "document_regions": [{"id": "region-1", "text": "系统必须安全"}],
        "stakeholders": [],
        "concerns": [],
        "needs": [],
        "claims": [],
        "structured_requirements": [],
        "scenarios": [],
        "discovery": {},
    }
    response = GenerationResponse(
        lens_id="requirements",
        payload={
            "schema_version": "v2",
            "block_id": "requirements",
            "input_hash": "input-1",
            "items": [
                {
                    "id": "req-1",
                    "subject": "系统",
                    "predicate": "必须",
                    "statement": "系统必须安全",
                    "verification_method": "test",
                    "source_region_ids": ["region-1"],
                    "confidence": 0.9,
                }
            ],
            "diagnostics": [],
        },
        input_hash="input-1",
        output_hash="output-1",
        repaired=False,
    )
    validated = validate_and_build_result(response, state=state, block_id="requirements")
    merged = merge_block_result(state, validated)

    assert merged is not state
    assert merged["claims"][0]["id"].startswith("requirement-")
    assert state["claims"] == []
