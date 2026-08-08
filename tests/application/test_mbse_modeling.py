import pytest

from rflp_lite.application.mbse_modeling import apply_mbse_edit, generate_mbse_revision
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


def test_mbse_edit_requires_current_revision():
    state = generate_mbse_revision(_reviewed_state())
    operation = {"kind": "rename", "id": state["mbse"]["use_cases"][0]["id"], "name": "新名称"}
    with pytest.raises(ContractViolation, match="revision"):
        apply_mbse_edit(state, "wrong", operation)

