import pytest

from rflp_lite.application.intelligence.review import edit_candidate, review_candidate
from rflp_lite.domain.errors import ContractViolation


def state():
    return {"discovery": {"revision": 4, "candidate_sets": [{"lens_id": "test", "items": [{"id": "parent", "element_type": "capability", "status": "candidate", "payload": {"name": "医疗运输", "verb": "运输", "object": "患者"}, "provenance": [{"source_type": "inferred", "source_id": "lens-capability", "rationale": "能力分析"}]}, {"id": "child", "element_type": "requirement", "status": "accepted", "payload": {"name": "响应要求", "statement": "系统应响应任务", "requirement_type": "operational", "verification_method": "test"}, "provenance": [{"source_type": "derived", "source_id": "parent", "rationale": "细化"}]}]}], "review_history": []}}


def test_review_requires_current_revision_and_records_history():
    with pytest.raises(ContractViolation, match="stale"):
        review_candidate(state(), "parent", "accepted", expected_revision=3)
    result = review_candidate(state(), "parent", "accepted", expected_revision=4)
    assert result["discovery"]["revision"] == 5
    assert result["discovery"]["candidate_sets"][0]["items"][0]["status"] == "accepted"
    assert result["discovery"]["review_history"][-1]["decision"] == "accepted"


def test_edit_returns_descendants_to_stale():
    pack = {"element_schemas": {"capability": {"required": ["name", "verb", "object"]}}}
    result = edit_candidate(state(), "parent", {"name": "紧急医疗运输", "verb": "运输", "object": "危重患者"}, 4, pack)
    items = {item["id"]: item for item in result["discovery"]["candidate_sets"][0]["items"]}
    assert items["parent"]["status"] == "accepted"
    assert items["child"]["status"] == "stale"
