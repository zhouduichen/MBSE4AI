from __future__ import annotations

import pytest

from rflp_lite.application.requirements_workbench import analyze_artifact
from rflp_lite.application.scenario_execution import (
    append_scenario_run,
    execute_scenario,
)
from rflp_lite.application.scenarios import add_scenario
from rflp_lite.domain.errors import ContractViolation


def _state(*, faults: str = "") -> dict[str, object]:
    state = analyze_artifact("requirements.txt", b"The service shall restore a version.")
    state = add_scenario(
        state,
        title="恢复版本",
        description="验证恢复流程",
        steps="选择版本\n确认恢复",
        expected_outcomes="内容恢复\n写入审计记录",
        faults=faults,
    )
    return state


def test_execute_scenario_returns_deterministic_declarative_trace():
    state = _state()
    scenario_id = state["scenarios"][0]["id"]

    first = execute_scenario(state, scenario_id)
    second = execute_scenario(state, scenario_id)

    assert first == second
    assert first["status"] == "completed"
    assert first["verification"] == "declarative-only"
    assert [item["kind"] for item in first["events"]] == [
        "step",
        "step",
        "expected_outcome",
        "expected_outcome",
    ]
    assert all(item["status"] == "not_verified" for item in first["assertions"])
    assert first["evidence"][0]["trace_hash"] == first["trace_hash"]


def test_execute_scenario_marks_faults_without_running_code():
    state = _state(faults="恢复失败")
    scenario_id = state["scenarios"][0]["id"]

    result = execute_scenario(state, scenario_id)

    assert result["status"] == "completed_with_faults"
    assert {item["status"] for item in result["events"] if item["kind"] == "fault"} == {
        "injected"
    }


def test_execute_unknown_scenario_is_rejected():
    with pytest.raises(ContractViolation, match="场景不存在"):
        execute_scenario(_state(), "scenario-missing")


def test_append_scenario_run_retains_latest_run():
    state = _state()
    scenario_id = state["scenarios"][0]["id"]
    result = execute_scenario(state, scenario_id)

    updated = append_scenario_run(state, result)

    assert updated["scenario_runs"] == [result]
    assert "scenario_runs" not in state or state["scenario_runs"] == []
