from __future__ import annotations

import pytest

from rflp_lite.application.requirements_workbench import add_stakeholder, analyze_artifact
from rflp_lite.application.scenarios import (
    add_scenario,
    build_scenario,
    delete_scenario,
    generate_scenario_drafts,
    generate_scenario_matrix,
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


def _matrix_pack():
    dimensions = {
        "weather": ["晴天", "雨天", "雷暴", "强风"],
        "visibility": ["正常", "夜间", "低能见度"],
        "mission_phase": ["接警", "城市巡航", "降落", "患者交接", "应急备降", "返航"],
        "system_state": ["正常", "降级", "部分失效", "完全失效", "失效安全"],
        "medical_urgency": ["常规转运", "危重", "生命垂危"],
        "urban_context": ["人口密集区", "狭窄起降点", "医院屋顶", "灾害封锁区"],
        "connectivity": ["全连接", "通信中断", "导航不可信", "GNSS受干扰"],
        "time": ["白天", "高峰", "灾害响应"],
    }
    return {
        "id": "urban-medical-aam-v1",
        "scenario_dimensions": [
            {"id": key, "label": key, "values": values}
            for key, values in dimensions.items()
        ],
        "lifecycle_phases": [{"id": "operation", "label": "运行"}],
    }


def test_system_generates_a_representative_scenario_matrix():
    generated = generate_scenario_matrix(_state(), _matrix_pack())
    scenarios = generated["scenarios"]

    assert 12 <= len(scenarios) <= 16
    assert all(item["status"] == "accepted" for item in scenarios)
    assert all(item["generation_mode"] == "scenario-matrix" for item in scenarios)
    assert {item["scenario_type"] for item in scenarios} >= {"normal", "exception", "failure", "emergency"}
    assert all(item["dimensions"] and item["requirement_ids"] for item in scenarios)
    assert len({item["id"] for item in scenarios}) == len(scenarios)


def test_scenario_matrix_preserves_manual_scenarios():
    state = add_scenario(
        _state(),
        title="人工定义的返航场景",
        description="飞行员人工确认返航。",
        steps="确认故障\n执行返航",
        expected_outcomes="安全返航",
        requirement_ids="req-restore",
    )
    state["scenarios"][0]["producer"] = "user"
    generated = generate_scenario_matrix(state, _matrix_pack())

    assert any(item["title"] == "人工定义的返航场景" for item in generated["scenarios"])
    assert len({item["id"] for item in generated["scenarios"]}) == len(generated["scenarios"])


def test_generated_scenario_is_accepted_and_executable():
    state = generate_scenario_drafts(_state())
    scenario = state["scenarios"][0]
    assert scenario["status"] == "accepted"
    result = execute_scenario(state, scenario["id"])
    assert result["verification"] == "declarative-only"

    state = review_scenario(state, scenario["id"], "rejected")
    assert state["scenarios"][0]["status"] == "rejected"


def test_editing_scenario_keeps_it_accepted_and_records_review():
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
    assert edited["status"] == "accepted"
    assert edited["title"] == "确认恢复"
    assert edited["revision"] == 2
    state = review_scenario(state, scenario["id"], "rejected")
    assert state["scenarios"][0]["status"] == "rejected"
    assert len(state["scenarios"][0]["review_history"]) == 2


def test_editing_generated_scenario_records_user_fields_and_resolves_suggestion():
    state = generate_scenario_drafts(add_stakeholder(_state(), "管理员"))
    stakeholder_id = state["stakeholders"][0]["id"]
    scenario = state["scenarios"][0]
    scenario["suggested_changes"] = [
        {
            "field": "title",
            "current": scenario["title"],
            "suggested": "人工确认恢复",
            "block_id": "scenarios",
            "input_hash": "input-1",
        },
        {
            "field": "description",
            "current": scenario["description"],
            "suggested": "保留的其他建议",
            "block_id": "scenarios",
            "input_hash": "input-1",
        },
    ]
    before_content_revision = state["content_revision"]

    edited = revise_scenario(
        state,
        scenario["id"],
        title="人工确认恢复",
        scenario_type="recovery",
        coverage_dimensions=["safety"],
        lifecycle_phase="operation",
        description=scenario["description"],
        trigger="检测到故障",
        actors=scenario["actors"],
        stakeholder_ids=[stakeholder_id],
        preconditions=scenario["preconditions"],
        steps=scenario["steps"],
        recovery_steps=["恢复服务"],
        expected_outcomes=scenario["expected_outcomes"],
        faults=scenario["faults"],
        requirement_ids=scenario["requirement_ids"],
    )

    current = edited["scenarios"][0]
    assert current["producer"] == scenario["producer"]
    assert current["last_editor"] == "user"
    assert current["field_sources"]["title"] == "user"
    assert current["field_sources"]["scenario_type"] == "user"
    assert current["scenario_type"] == "recovery"
    assert current["coverage_dimensions"] == ["safety"]
    assert current["lifecycle_phase"] == "operation"
    assert current["trigger"] == "检测到故障"
    assert current["stakeholder_ids"] == [stakeholder_id]
    assert current["recovery_steps"] == ["恢复服务"]
    assert [item["field"] for item in current["suggested_changes"]] == [
        "description"
    ]
    assert current["suggestion_history"][0]["status"] == "accepted_by_user"
    assert edited["content_revision"] == before_content_revision + 1


def test_manual_scenario_initializes_user_provenance_and_validates_relations():
    state = add_stakeholder(_state(), "管理员")
    stakeholder_id = state["stakeholders"][0]["id"]

    created = add_scenario(
        state,
        title="恢复流程",
        scenario_type="recovery",
        coverage_dimensions="safety\ncybersecurity",
        lifecycle_phase="operation",
        description="管理员恢复服务。",
        trigger="服务故障",
        actors="管理员\n系统",
        stakeholder_ids=[stakeholder_id],
        steps="选择版本\n确认恢复",
        recovery_steps="恢复服务",
        expected_outcomes="服务恢复",
        requirement_ids="req-restore",
    )

    scenario = created["scenarios"][0]
    assert scenario["producer"] == "user"
    assert scenario["last_editor"] == "user"
    assert scenario["field_sources"]["coverage_dimensions"] == "user"
    assert scenario["coverage_dimensions"] == ["safety", "cybersecurity"]
    assert created["content_revision"] == state["content_revision"] + 1

    with pytest.raises(ContractViolation, match="利益相关方"):
        add_scenario(
            state,
            title="错误关联",
            description="关联不存在的利益相关方。",
            stakeholder_ids=["stakeholder-missing"],
            steps="执行",
            expected_outcomes="完成",
        )


def test_reviewing_scenario_marks_status_as_user_authored_and_invalidates_coverage():
    state = generate_scenario_drafts(_state())
    state["analysis_coverage"] = {"missing_scenario_types": []}
    scenario = state["scenarios"][0]

    reviewed = review_scenario(state, scenario["id"], "rejected")

    current = reviewed["scenarios"][0]
    assert current["field_sources"]["status"] == "user"
    assert current["last_editor"] == "user"
    assert reviewed["analysis_coverage"] == {}
    assert reviewed["content_revision"] == state["content_revision"] + 1
