from __future__ import annotations

from rflp_lite.application.sequence_layout import layout_sequence
from rflp_lite.application.sequence_modeling import build_sequence_interaction
from rflp_lite.application.sequence_render import render_sequence_svg


def interaction_fixture(message_count: int = 2) -> dict[str, object]:
    steps = [
        "用户 -> 系统：提交请求",
        "系统 -> 数据库：查询数据",
        "系统 -> 用户：返回结果",
    ][:message_count]
    return build_sequence_interaction(
        {
            "scenarios": [
                {
                    "id": "scenario-render",
                    "title": "渲染场景",
                    "status": "accepted",
                    "revision": 1,
                    "hash": "render-hash",
                    "actors": ["用户"],
                    "steps": steps,
                    "requirement_ids": [],
                }
            ]
        },
        "scenario-render",
    )


def test_sequence_svg_contains_real_arrow_markers_and_lifelines():
    interaction = interaction_fixture(message_count=2)
    interaction["messages"][1]["sort"] = "reply"
    svg = render_sequence_svg(layout_sequence(interaction))
    assert "<svg" in svg
    assert 'marker-end="url(#arrow-filled)"' in svg
    assert 'marker-end="url(#arrow-open)"' in svg
    assert 'stroke-dasharray="6 5"' in svg
    assert "Sequence Diagram" in svg


def test_reply_is_dashed_and_candidate_is_visible():
    interaction = interaction_fixture(message_count=1)
    interaction["messages"][0]["sort"] = "reply"
    interaction["messages"][0]["status"] = "candidate"
    svg = render_sequence_svg(layout_sequence(interaction))
    assert 'stroke-dasharray="8 5"' in svg
    assert 'class="message candidate"' in svg


def test_sequence_svg_escapes_user_text_and_draws_self_call():
    interaction = interaction_fixture(message_count=1)
    interaction["messages"][0]["name"] = "<危险>"
    interaction["messages"][0]["sender_lifeline_id"] = interaction["messages"][0]["receiver_lifeline_id"]
    svg = render_sequence_svg(layout_sequence(interaction))
    assert "&lt;危险&gt;" in svg
    assert "<危险>" not in svg
    assert 'class="self-call"' in svg
