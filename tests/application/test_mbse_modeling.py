import pytest

from rflp_lite.application.mbse_modeling import (
    apply_mbse_edit,
    confirm_mbse,
    generate_mbse_revision,
    review_mbse_element,
)
from rflp_lite.application.mbse_semantics import mbse_entity_index
from rflp_lite.application.requirements_workbench import analyze_artifact, accept_traceable
from rflp_lite.domain.errors import ContractViolation


def _reviewed_state():
    state = analyze_artifact("requirements.txt", "支持导入 PDF。".encode())
    return accept_traceable(state)


def test_accepted_requirement_generates_all_three_model_views():
    state = generate_mbse_revision(_reviewed_state())
    model = state["mbse"]
    assert model["actors"]
    assert model["use_cases"]
    assert model["activities"]
    assert model["messages"]
    assert model["trace_links"]
    assert model["status"] == "accepted"


def test_mbse_elements_can_be_reviewed_and_model_confirmed():
    state = generate_mbse_revision(_reviewed_state())
    use_case_id = state["mbse"]["use_cases"][0]["id"]
    state = review_mbse_element(state, use_case_id, "accepted")
    assert state["mbse"]["use_cases"][0]["status"] == "accepted"
    state = confirm_mbse(state)
    assert state["mbse"]["status"] == "accepted"
    assert all(
        item["status"] in {"accepted", "needs-analysis"}
        for collection in ("actors", "use_cases", "activities", "lifelines", "messages")
        for item in state["mbse"][collection]
    )
    assert any(item["status"] == "needs-analysis" for item in state["mbse"]["activities"])


def test_mbse_confirmation_rejects_required_view():
    state = generate_mbse_revision(_reviewed_state())
    activity_id = state["mbse"]["activities"][0]["id"]
    state = review_mbse_element(state, activity_id, "rejected")
    with pytest.raises(ContractViolation, match="已驳回"):
        confirm_mbse(state)


def test_mbse_generation_skips_orphaned_need_relations():
    state = accept_traceable(
        analyze_artifact("requirements.txt", "管理员必须恢复历史版本。".encode())
    )
    state["concerns"] = []
    state["needs"][0]["concern_id"] = "missing-concern"

    generated = generate_mbse_revision(state)

    relations = generated["mbse"]["semantic_model"]["relations"]
    entity_ids = set(mbse_entity_index(generated["mbse"]["semantic_model"]))
    assert relations
    assert all(
        relation["source_id"] in entity_ids and relation["target_id"] in entity_ids
        for relation in relations
    )


def test_mbse_edit_requires_current_revision():
    state = generate_mbse_revision(_reviewed_state())
    operation = {"kind": "rename", "id": state["mbse"]["use_cases"][0]["id"], "name": "新名称"}
    with pytest.raises(ContractViolation, match="revision"):
        apply_mbse_edit(state, "wrong", operation)


def test_mbse_edit_returns_model_to_review_after_rename():
    state = confirm_mbse(generate_mbse_revision(_reviewed_state()))
    item = state["mbse"]["use_cases"][0]
    edited = apply_mbse_edit(
        state,
        state["mbse"]["revision"],
        {"kind": "rename", "id": item["id"], "name": "修改后的用例"},
    )
    assert edited["mbse"]["status"] == "review"
    assert edited["mbse"]["use_cases"][0]["status"] == "accepted"
