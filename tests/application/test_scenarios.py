from __future__ import annotations

import pytest

from rflp_lite.application.requirements_workbench import analyze_artifact
from rflp_lite.application.scenarios import add_scenario, build_scenario, delete_scenario
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
