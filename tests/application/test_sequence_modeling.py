from __future__ import annotations

import pytest

from rflp_lite.application.sequence_modeling import build_sequence_interaction
from rflp_lite.domain.errors import ContractViolation


def accepted_scenario_state() -> dict[str, object]:
    return {
        "scenarios": [
            {
                "id": "scenario-login",
                "title": "用户登录",
                "description": "验证登录流程",
                "status": "accepted",
                "revision": 2,
                "hash": "scenario-hash",
                "actors": ["用户"],
                "steps": [
                    "用户 -> 系统：提交登录",
                    "系统 -> 数据库：查询用户",
                    "系统 -> 用户：返回结果",
                ],
                "requirement_ids": ["req-login"],
            }
        ],
        "claims": [{"id": "req-login", "status": "accepted"}],
    }


def test_build_sequence_interaction_is_scenario_scoped_and_ordered():
    result = build_sequence_interaction(accepted_scenario_state(), "scenario-login")
    assert result["source_scenario_id"] == "scenario-login"
    assert [
        item["order"] for item in result["occurrences"] if item["kind"] == "send"
    ] == [1, 2, 3]
    names = {item["name"]: item["id"] for item in result["lifelines"]}
    first = result["messages"][0]
    assert first["sender_lifeline_id"] == names["用户"]
    assert first["receiver_lifeline_id"] == names["系统"]
    assert result["status"] == "ready"


def test_build_sequence_interaction_requires_accepted_scenario():
    state = accepted_scenario_state()
    state["scenarios"][0]["status"] = "draft"
    with pytest.raises(ContractViolation, match="尚未确认"):
        build_sequence_interaction(state, "scenario-login")


def test_unstructured_step_is_candidate_and_does_not_claim_ready():
    state = accepted_scenario_state()
    state["scenarios"][0]["steps"] = ["处理请求"]
    result = build_sequence_interaction(state, "scenario-login")
    assert result["status"] == "candidate"
    assert result["messages"][0]["status"] == "candidate"


def test_structured_interaction_steps_preserve_sort_and_guard():
    state = accepted_scenario_state()
    state["scenarios"][0]["interaction_steps"] = [
        {
            "order": 1,
            "sender": "用户",
            "receiver": "系统",
            "message": "提交登录",
            "sort": "async_call",
            "guard": "[网络可用]",
        }
    ]
    result = build_sequence_interaction(state, "scenario-login")
    assert result["messages"][0]["sort"] == "async_call"
    assert result["messages"][0]["guard"] == "[网络可用]"


def test_unknown_scenario_is_rejected():
    with pytest.raises(ContractViolation, match="场景不存在"):
        build_sequence_interaction(accepted_scenario_state(), "scenario-missing")
