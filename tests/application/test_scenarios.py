from __future__ import annotations

import pytest

from rflp_lite.application.requirements_workbench import analyze_artifact
from rflp_lite.application.scenarios import (
    add_scenario,
    build_scenario,
    delete_scenario,
    generate_scenario_drafts,
    revise_scenario,
    review_scenario,
)
from rflp_lite.application.scenario_execution import execute_scenario
from rflp_lite.domain.errors import ContractViolation


def _state():
    state = analyze_artifact(
        "requirements.txt", "The service shall restore a historical version.".encode()
    )
    state["claims"][0]["id"] = "req-restore"
    return state


def test_build_scenario_normalizes_lines_and_is_deterministic():
    first = build_scenario(
        title="恢复历史版本",
        description="用户请求恢复一个历史版本。",
        actors="管理员\n普通用户",
        preconditions="版本存在\n",
        steps="选择版本\n确认恢复",
        expected_outcomes="内容恢复\n写入审计记录",
        faults="恢复失败时重试一次",
    )
    second = build_scenario(
        title="恢复历史版本",
        description="用户请求恢复一个历史版本。",
        actors=["管理员", "普通用户"],
        preconditions=["版本存在"],
        steps=["选择版本", "确认恢复"],
        expected_outcomes=["内容恢复", "写入审计记录"],
        faults=["恢复失败时重试一次"],
    )
    assert first == second
    assert first["id"].startswith("scenario-")


def test_add_and_delete_scenario_preserve_workbench_state():
    state = _state()
    state = add_scenario(
        state,
        title="恢复历史版本",
        description="管理员恢复历史版本。",
        steps="选择版本\n确认恢复",
        expected_outcomes="内容恢复",
        requirement_ids="req-restore",
    )
    scenario_id = state["scenarios"][0]["id"]
    assert state["claims"][0]["id"] == "req-restore"
    state = delete_scenario(state, scenario_id)
    assert state["scenarios"] == []


def test_scenario_requires_steps_and_known_requirements():
    state = _state()
    with pytest.raises(ContractViolation, match="步骤"):
        add_scenario(
            state,
            title="恢复",
            description="描述",
            steps="",
            expected_outcomes="完成",
        )
    with pytest.raises(ContractViolation, match="不存在"):
        add_scenario(
            state,
            title="恢复",
            description="描述",
            steps="执行",
            expected_outcomes="完成",
            requirement_ids="req-missing",
        )


def test_delete_unknown_scenario_is_rejected():
    with pytest.raises(ContractViolation, match="场景不存在"):
        delete_scenario(_state(), "scenario-missing")


def test_system_generates_a_scenario_from_minimum_natural_language_input():
    state = analyze_artifact("requirements.txt", "设置一个航天系统".encode())

    generated = generate_scenario_drafts(state)

    assert len(generated["scenarios"]) == 1
    scenario = generated["scenarios"][0]
    assert scenario["producer"] == "system"
    assert scenario["generation_mode"] == "minimum-input"
    assert "航天系统" in scenario["title"]
    assert scenario["steps"]
    assert scenario["expected_outcomes"]
    assert all(item["status"] == "candidate" for item in state["claims"])


def test_generated_scenario_requires_review_before_execution():
    state = generate_scenario_drafts(_state())
    scenario = state["scenarios"][0]
    with pytest.raises(ContractViolation, match="尚未确认"):
        execute_scenario(state, scenario["id"])

    state = review_scenario(state, scenario["id"], "accepted")
    assert state["scenarios"][0]["status"] == "accepted"
    result = execute_scenario(state, scenario["id"])
    assert result["verification"] == "declarative-only"


def test_editing_scenario_returns_it_to_review_and_records_decision():
    state = generate_scenario_drafts(_state())
    scenario = state["scenarios"][0]
    state = review_scenario(state, scenario["id"], "accepted")
    state = revise_scenario(
        state,
        scenario["id"],
        title="确认恢复",
        description="管理员确认恢复历史版本。",
        actors="管理员\n系统",
        preconditions="版本存在",
        steps="选择版本\n确认恢复",
        expected_outcomes="内容恢复",
        faults="恢复失败时记录故障",
    )
    edited = state["scenarios"][0]
    assert edited["status"] == "draft"
    assert edited["title"] == "确认恢复"
    assert edited["revision"] == 2
    state = review_scenario(state, scenario["id"], "rejected")
    assert state["scenarios"][0]["status"] == "rejected"
    assert len(state["scenarios"][0]["review_history"]) == 2
