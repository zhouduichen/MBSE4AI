import pytest

from rflp_lite.application.mbse_modeling import (
    apply_mbse_edit,
    confirm_mbse,
    generate_mbse_revision,
    review_mbse_element,
)
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
        item["status"] == "accepted"
        for collection in ("actors", "use_cases", "activities", "lifelines", "messages")
        for item in state["mbse"][collection]
    )


def test_mbse_confirmation_rejects_required_view():
    state = generate_mbse_revision(_reviewed_state())
    activity_id = state["mbse"]["activities"][0]["id"]
    state = review_mbse_element(state, activity_id, "rejected")
    with pytest.raises(ContractViolation, match="已驳回"):
        confirm_mbse(state)


def test_mbse_edit_requires_current_revision():
    state = generate_mbse_revision(_reviewed_state())
    operation = {"kind": "rename", "id": state["mbse"]["use_cases"][0]["id"], "name": "新名称"}
    with pytest.raises(ContractViolation, match="revision"):
        apply_mbse_edit(state, "wrong", operation)


def test_mbse_edit_keeps_model_accepted_after_rename():
    state = confirm_mbse(generate_mbse_revision(_reviewed_state()))
    item = state["mbse"]["use_cases"][0]
    edited = apply_mbse_edit(
        state,
        state["mbse"]["revision"],
        {"kind": "rename", "id": item["id"], "name": "修改后的用例"},
    )
    assert edited["mbse"]["status"] == "accepted"
    assert edited["mbse"]["use_cases"][0]["status"] == "accepted"
