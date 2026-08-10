"""Deterministic geometry for sequence interaction diagrams."""

from __future__ import annotations

from collections.abc import Mapping

from rflp_lite.domain.errors import ContractViolation
from rflp_lite.domain.sequence import message_sort_style, validate_sequence_interaction


LEFT = 64.0
TOP = 40.0
HEADER_HEIGHT = 42.0
MESSAGE_TOP = 128.0
MESSAGE_GAP = 72.0
LIFELINE_GAP = 220.0
BOTTOM = 64.0


def _message_style(sort: str) -> tuple[str, str, str]:
    style = message_sort_style(sort)
    if style == "sync-call":
        return "filled", "solid", "sync-call"
    if style == "async-call":
        return "open", "solid", "async-call"
    return "open", "dashed", style


def _send_order(interaction: Mapping[str, object]) -> dict[str, int | float]:
    return {
        str(item["id"]): item.get("order", 0)
        for item in interaction["occurrences"]
        if item.get("kind") == "send"
    }


def _fragment_layout(
    interaction: Mapping[str, object],
    message_rows: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    fragments = {str(item["id"]): item for item in interaction["fragments"]}
    message_y = {str(item["id"]): float(item["y"]) for item in message_rows.values()}
    combined_by_id = {
        str(item["id"]): item for item in interaction.get("combined_fragments", ())
    }
    operand_by_id = {str(item["id"]): item for item in interaction.get("operands", ())}
    result: list[dict[str, object]] = []
    for combined_id, combined in combined_by_id.items():
        child_fragment_ids: list[str] = []
        for operand_id in combined.get("operand_ids", ()):
            operand = operand_by_id.get(str(operand_id))
            if operand is None:
                raise ContractViolation("combined fragment operand is invalid")
            child_fragment_ids.extend(str(item) for item in operand.get("fragment_ids", ()))
        child_message_ids = [
            str(fragments[item_id]["message_id"])
            for item_id in child_fragment_ids
            if item_id in fragments and fragments[item_id].get("kind") == "message"
        ]
        if not child_message_ids or not all(item in message_y for item in child_message_ids):
            raise ContractViolation("combined fragment has no resolvable child fragment")
        ys = [message_y[item] for item in child_message_ids]
        result.append(
            {
                "id": combined_id,
                "operator": str(combined["operator"]),
                "x": LEFT - 24.0,
                "y": min(ys) - 34.0,
                "width": max(720.0, float(interaction.get("width", 720.0))) - LEFT + 24.0,
                "height": max(52.0, max(ys) - min(ys) + 68.0),
                "operand_separator_y": [
                    message_y[item] + MESSAGE_GAP / 2.0 for item in child_message_ids[:-1]
                ],
            }
        )
    return result


def layout_sequence(interaction: dict[str, object]) -> dict[str, object]:
    normalized = validate_sequence_interaction(interaction)
    lifeline_items = list(normalized["lifelines"])
    width = max(720.0, LEFT * 2 + max(0, len(lifeline_items) - 1) * LIFELINE_GAP + 120.0)
    send_orders = _send_order(normalized)
    ordered_messages = sorted(
        normalized["messages"],
        key=lambda item: (float(send_orders.get(str(item["send_occurrence_id"]), 0)), str(item["id"])),
    )
    message_count = len(ordered_messages)
    height = max(240.0, MESSAGE_TOP + max(1, message_count) * MESSAGE_GAP + BOTTOM)
    x_by_id = {
        str(item["id"]): LEFT + index * LIFELINE_GAP
        for index, item in enumerate(lifeline_items)
    }
    lifelines = [
        {
            "id": str(item["id"]),
            "name": str(item.get("name", item["id"])),
            "kind": str(item.get("kind", "actor")),
            "x": x_by_id[str(item["id"])],
            "header_y": TOP,
            "line_y1": TOP + HEADER_HEIGHT,
            "line_y2": height - BOTTOM / 2,
        }
        for item in lifeline_items
    ]
    message_rows: list[dict[str, object]] = []
    message_by_id: dict[str, dict[str, object]] = {}
    for index, item in enumerate(ordered_messages):
        sender_id = str(item["sender_lifeline_id"])
        receiver_id = str(item["receiver_lifeline_id"])
        x1 = x_by_id[sender_id]
        x2 = x_by_id[receiver_id]
        y = MESSAGE_TOP + index * MESSAGE_GAP
        arrow_style, line_style, style_name = _message_style(str(item["sort"]))
        row: dict[str, object] = {
            "id": str(item["id"]),
            "name": str(item.get("name", "")),
            "sort": str(item["sort"]),
            "x1": x1,
            "x2": x2,
            "y": y,
            "text_x": min(x1, x2) + abs(x2 - x1) / 2.0,
            "text_y": y - 10.0,
            "arrow_style": arrow_style,
            "line_style": line_style,
            "style_name": style_name,
            "candidate": item.get("status") == "candidate",
            "guard": item.get("guard"),
            "self_call": x1 == x2,
            "loop_x": x1 + 72.0 if x1 == x2 else None,
        }
        message_rows.append(row)
        message_by_id[str(item["id"])] = row

    executions: list[dict[str, object]] = []
    message_y = {str(item["id"]): float(item["y"]) for item in message_rows}
    for execution in normalized["executions"]:
        start = next(
            item for item in normalized["occurrences"] if item["id"] == execution["start_occurrence_id"]
        )
        message_id = str(start["message_id"])
        y = message_y.get(message_id)
        if y is None:
            raise ContractViolation("execution message reference is invalid")
        later_y = min(
            (float(item["y"]) for item in message_rows if float(item["y"]) > y),
            default=y + 48.0,
        )
        executions.append(
            {
                "id": str(execution["id"]),
                "x": x_by_id[str(execution["lifeline_id"])] - 7.0,
                "y": y - 10.0,
                "width": 14.0,
                "height": max(36.0, later_y - y + 20.0),
                "depth": int(execution.get("depth", 0)),
            }
        )

    layout: dict[str, object] = {
        "width": width,
        "height": height,
        "title": str(normalized.get("name", "Sequence Diagram")),
        "status": normalized.get("status", "candidate"),
        "lifelines": lifelines,
        "messages": message_rows,
        "executions": executions,
        "fragments": _fragment_layout({**normalized, "width": width}, message_by_id),
        "legend": {"sync": "同步调用", "async": "异步消息", "reply": "返回消息"},
    }
    return layout
