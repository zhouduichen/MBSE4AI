import pytest

from rflp_lite.application.requirements_workbench import (
    accept_traceable,
    add_llm_suggestions,
    analyze_artifact,
    generate_model,
)
from rflp_lite.domain.errors import AdapterFailure


def test_reviewed_stakeholders_generate_stable_dynamic_rflp(monkeypatch):
    source = (
        "管理员必须恢复历史版本。\n"
        "审计人员必须查看恢复记录。\n"
        "普通用户应当只能查看自己的内容。"
    ).encode()

    state = analyze_artifact("requirements.txt", source)

    assert {item["name"] for item in state["stakeholders"]} >= {
        "管理员",
        "审计人员",
        "普通用户",
    }
    state = accept_traceable(state)
    state = generate_model(state)
    assert {item["layer"] for item in state["rflp"]["elements"]} == {
        "R",
        "F",
        "L",
        "P",
    }
    assert state["coverage"] == {"R-F": 100, "F-L": 100, "L-P": 100}
    assert state["svg"] == generate_model(state)["svg"]
    assert "管理员" in state["svg"]

    monkeypatch.delenv("RFLP_LLM_API_KEY", raising=False)
    with pytest.raises(AdapterFailure, match="LLM 未配置"):
        add_llm_suggestions(state)


def test_inferred_stakeholder_is_not_automatically_accepted():
    state = analyze_artifact("requirements.txt", "系统必须保留审计记录。".encode())
    state["stakeholders"].append(
        {
            "id": "stakeholder-inferred",
            "name": "审计人员",
            "candidate_type": "inferred",
            "source_span_id": state["spans"][0]["id"],
            "confidence": 0.7,
            "reason": "由审计要求推断",
            "producer": "llm",
            "status": "candidate",
        }
    )

    accepted = accept_traceable(state)

    assert accepted["stakeholders"][-1]["status"] == "candidate"
