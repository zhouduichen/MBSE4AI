from rflp_lite.application.requirements_flow import run_requirements_flow
from rflp_lite.application.requirements_workbench import analyze_artifact
from rflp_lite.application.scenarios import add_scenario


def test_requirements_flow_builds_model_scenarios_and_local_traces_from_input():
    state = analyze_artifact(
        "requirements.txt",
        "管理员必须恢复历史版本。\n审计人员必须查看恢复记录。".encode(),
    )

    result = run_requirements_flow(state)

    assert result["flow"]["status"] == "completed"
    assert result["baseline"]["approval_mode"] == "quick-flow"
    assert result["rflp"]["elements"]
    assert len(result["scenarios"]) == 2
    assert len(result["scenario_runs"]) == 2
    assert all(item["producer"] == "rule" for item in result["scenarios"])
    assert all(item["verification"] == "declarative-only" for item in result["scenario_runs"])


def test_requirements_flow_keeps_plain_language_as_a_reviewable_draft():
    state = analyze_artifact("requirements.txt", "希望系统支持历史版本恢复。".encode())

    result = run_requirements_flow(state)

    assert result["flow"]["status"] == "draft_only"
    assert result["draft"] is True
    assert result["rflp"] is None
    assert result["draft_graph"]["items"]
    assert "需求理解图" in result["svg"]
    assert result["scenarios"]
    assert result["scenario_runs"]


def test_requirements_flow_turns_a_broad_system_intent_into_a_named_starter_context():
    state = analyze_artifact("requirements.txt", "设置一个航天系统".encode())

    result = run_requirements_flow(state)

    assert result["system_context"]["name"] == "航天系统"
    assert result["system_context"]["domain"] == "航天"
    assert result["scenarios"][0]["title"] == "航天系统定义"
    assert result["scenario_runs"][0]["verification"] == "declarative-only"
    assert "航天系统" in result["svg"]
    assert result["flow"]["next_action"]


def test_requirements_flow_executes_existing_scenarios_without_creating_duplicates():
    state = analyze_artifact("requirements.txt", "管理员必须恢复历史版本。".encode())
    claim_id = state["claims"][0]["id"]
    state = add_scenario(
        state,
        title="人工补充恢复流程",
        description="补充更具体的验证步骤。",
        steps=("选择版本", "确认恢复"),
        expected_outcomes=("恢复成功",),
        requirement_ids=(claim_id,),
    )

    result = run_requirements_flow(state)

    assert len(result["scenarios"]) == 1
    assert len(result["scenario_runs"]) == 1
