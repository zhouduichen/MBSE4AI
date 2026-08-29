from __future__ import annotations

from rflp_lite.interface.web.presenters import analysis_blocks_context, provenance_context


def test_analysis_progress_maps_internal_ids_and_retryable_states() -> None:
    state = {
        "auto_analysis": {
            "blocks": {"architecture": "failed", "requirements": "succeeded"},
            "diagnostics": [{"block_id": "architecture", "message": "关系端点不合法"}],
        }
    }
    values = analysis_blocks_context(state)
    architecture = next(item for item in values if item["id"] == "architecture")
    assert architecture["label"] == "架构分析"
    assert architecture["status_label"] == "失败"
    assert architecture["retryable"] is True
    assert architecture["diagnostic"]["message"] == "关系端点不合法"


def test_provenance_is_available_for_review_pages() -> None:
    state = {
        "discovery": {
            "block_results": {
                "requirements": {"output_hash": "out-1", "repaired": False}
            }
        }
    }
    values = provenance_context(state)
    assert values[0]["label"] == "需求补全"
    assert values[0]["result"]["output_hash"] == "out-1"
