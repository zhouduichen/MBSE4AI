from __future__ import annotations

from copy import deepcopy

import pytest

from rflp_lite.application.sequence_layout import layout_sequence
from rflp_lite.application.sequence_modeling import build_sequence_interaction
from rflp_lite.domain.errors import ContractViolation


def interaction_fixture(message_count: int = 2) -> dict[str, object]:
    steps = [
        "用户 -> 系统：提交请求",
        "系统 -> 数据库：查询数据",
        "系统 -> 用户：返回结果",
    ][:message_count]
    state = {
        "scenarios": [
            {
                "id": "scenario-layout",
                "title": "布局场景",
                "status": "accepted",
                "revision": 1,
                "hash": "layout-hash",
                "actors": ["用户"],
                "steps": steps,
                "requirement_ids": [],
            }
        ]
    }
    return build_sequence_interaction(state, "scenario-layout")


def test_layout_places_lifelines_horizontally_and_messages_top_to_bottom():
    layout = layout_sequence(interaction_fixture(message_count=2))
    assert [item["x"] for item in layout["lifelines"]] == sorted(
        item["x"] for item in layout["lifelines"]
    )
    assert [item["y"] for item in layout["messages"]] == [128.0, 200.0]
    assert layout["height"] >= 280.0


def test_layout_assigns_reply_style_without_rewriting_semantics():
    interaction = interaction_fixture(message_count=2)
    interaction["messages"][1]["sort"] = "reply"
    layout = layout_sequence(interaction)
    assert layout["messages"][1]["arrow_style"] == "open"
    assert layout["messages"][1]["line_style"] == "dashed"
    assert interaction["messages"][1]["sort"] == "reply"


def test_layout_is_deterministic_for_same_interaction():
    interaction = interaction_fixture(message_count=2)
    assert layout_sequence(interaction) == layout_sequence(deepcopy(interaction))


def test_layout_marks_self_call_and_emits_loop_coordinate():
    interaction = interaction_fixture(message_count=1)
    message = interaction["messages"][0]
    message["receiver_lifeline_id"] = message["sender_lifeline_id"]
    layout = layout_sequence(interaction)
    assert layout["messages"][0]["self_call"] is True
    assert layout["messages"][0]["loop_x"] > layout["messages"][0]["x1"]


def test_layout_rejects_combined_fragment_without_child_message():
    interaction = interaction_fixture(message_count=1)
    interaction["combined_fragments"] = [
        {"id": "combined-1", "operator": "alt", "operand_ids": ["operand-1"]}
    ]
    interaction["operands"] = [{"id": "operand-1", "fragment_ids": ["missing"]}]
    interaction["fragments"].append(
        {"id": "fragment-combined", "kind": "combined", "combined_fragment_id": "combined-1", "order": 2}
    )
    with pytest.raises(ContractViolation, match="fragment"):
        layout_sequence(interaction)
