import pytest

from rflp_lite.application.requirements_workbench import (
    accept_traceable,
    add_llm_suggestions,
    analyze_artifact,
    add_stakeholder,
    generate_draft_model,
    generate_model,
    empty_workbench,
    merge_artifact,
    stakeholder_bundle,
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


def test_draft_model_is_available_before_review_without_mutating_candidates():
    state = analyze_artifact("requirements.txt", "管理员必须恢复历史版本。".encode())

    draft = generate_draft_model(state)

    assert draft["draft"] is True
    assert draft["rflp"]["elements"]
    assert draft["svg"].startswith("<svg")
    assert all(item["status"] == "candidate" for item in draft["claims"])
    assert state["rflp"] is None


def test_draft_model_accepts_plain_language_as_provisional_nodes():
    state = analyze_artifact("requirements.txt", "希望系统支持历史版本恢复。".encode())

    draft = generate_draft_model(state)

    assert state["claims"] == []
    assert draft["draft"] is True
    assert "没有明确的必须/应当" in draft["draft_warnings"][0]
    assert any("历史版本恢复" in item["name"] for item in draft["rflp"]["elements"])


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


def test_merge_artifact_accumulates_candidates_and_dedups():
    first = analyze_artifact("a.txt", "管理员必须恢复历史版本。\n".encode())
    second_fresh = analyze_artifact("b.txt", "审计人员必须查看恢复记录。\n".encode())

    merged = merge_artifact(first, "b.txt", "审计人员必须查看恢复记录。\n".encode())
    assert {item["name"] for item in merged["stakeholders"]} >= {"管理员", "审计人员"}
    assert {item["id"] for item in merged["spans"]} == {item["id"] for item in first["spans"]} | {
        item["id"] for item in second_fresh["spans"]
    }
    assert merged["rflp"] is None
    assert merged["baseline"] is None

    again = merge_artifact(merged, "a.txt", "管理员必须恢复历史版本。\n".encode())
    assert len(again["spans"]) == len(merged["spans"])


def test_manual_stakeholder_bundle_collects_related_objects():
    state = analyze_artifact(
        "requirements.txt",
        "管理员必须恢复历史版本。\n".encode(),
    )
    state = add_stakeholder(state, "产品负责人")
    state = add_stakeholder(state, "管理员")
    bundle = stakeholder_bundle(state, "管理员")

    assert bundle["selected"]["name"] == "管理员"
    assert bundle["concerns"][0]["name"] == "故障恢复"
    assert bundle["needs"][0]["statement"] == "管理员必须恢复历史版本。"
    assert bundle["claims"][0]["subject"] == "管理员"
    assert any(item["name"] == "产品负责人" for item in state["stakeholders"])


def test_manual_stakeholder_can_start_an_empty_workbench():
    state = add_stakeholder(empty_workbench(), "运维人员")

    assert state["artifact"]["kind"] == "manual"
    assert state["stakeholders"][0]["name"] == "运维人员"
    assert stakeholder_bundle(state)["selected"]["name"] == "运维人员"
