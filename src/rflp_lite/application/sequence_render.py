"""Deterministic SVG renderer for UML-style sequence layouts."""

from __future__ import annotations

from html import escape

from rflp_lite.application.sequence_svg import number, svg_line, svg_path, svg_rect, svg_text


def _marker_defs() -> str:
    return (
        '<marker id="arrow-filled" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto" markerUnits="strokeWidth">'
        '<path d="M 0 0 L 10 5 L 0 10 Z" fill="#263238"/></marker>'
        '<marker id="arrow-open" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto" markerUnits="strokeWidth">'
        '<path d="M 0 0 L 10 5 L 0 10" fill="none" stroke="#263238" stroke-width="1.4"/></marker>'
    )


def _message_line(row: dict[str, object]) -> str:
    arrow = f"arrow-{row['arrow_style']}"
    class_name = "message candidate" if row.get("candidate") else "message"
    if row.get("self_call"):
        x1 = float(row["x1"])
        loop_x = float(row["loop_x"])
        y = float(row["y"])
        path = f"M {number(x1)} {number(y)} L {number(loop_x)} {number(y)} L {number(loop_x)} {number(y + 24)} L {number(x1)} {number(y + 24)}"
        return svg_path(path, style=str(row["line_style"]), arrow=arrow, class_name="self-call")
    return svg_line(
        float(row["x1"]),
        float(row["y"]),
        float(row["x2"]),
        float(row["y"]),
        style=str(row["line_style"]),
        arrow=arrow,
        class_name=class_name,
    )


def render_sequence_svg(layout: dict[str, object]) -> str:
    width = float(layout["width"])
    height = float(layout["height"])
    title = str(layout.get("title", "Sequence Diagram"))
    title_id = "sequence-diagram-title"
    parts = [
        f'<svg class="sequence-svg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {number(width)} {number(height)}" role="img" aria-labelledby="{title_id}">',
        f'<title id="{title_id}">Sequence Diagram: {escape(title, quote=False)}</title>',
        f"<defs>{_marker_defs()}</defs>",
        svg_rect(0, 0, width, height, fill="#ffffff", stroke="#d9e2e5", radius=12, class_name="sequence-background"),
        '<g class="combined-fragments">',
    ]
    for fragment in layout.get("fragments", ()):
        parts.append(
            svg_rect(
                float(fragment["x"]),
                float(fragment["y"]),
                float(fragment["width"]),
                float(fragment["height"]),
                fill="#f8fbfb",
                stroke="#607d80",
                radius=4,
                class_name=f"combined-fragment {fragment['operator']}",
            )
        )
        parts.append(
            svg_text(
                float(fragment["x"]) + 10,
                float(fragment["y"]) + 18,
                str(fragment["operator"]),
                fill="#0b6b5a",
                size=12,
                weight="700",
                class_name="fragment-operator",
            )
        )
        for separator_y in fragment.get("operand_separator_y", ()):
            parts.append(
                svg_line(
                    float(fragment["x"]),
                    float(separator_y),
                    float(fragment["x"]) + float(fragment["width"]),
                    float(separator_y),
                    style="solid",
                    stroke="#9aaeb0",
                    width=1.0,
                    class_name="operand-separator",
                )
            )
    parts.append("</g>")
    parts.append('<g class="lifelines">')
    for lifeline in layout.get("lifelines", ()):
        x = float(lifeline["x"])
        parts.append(svg_rect(x - 58, float(lifeline["header_y"]), 116, 30, fill="#eef5f4", stroke="#47746c", radius=5, class_name="lifeline-header"))
        parts.append(svg_text(x, float(lifeline["header_y"]) + 20, lifeline["name"], fill="#173b37", size=12, weight="700", anchor="middle"))
        parts.append(svg_line(x, float(lifeline["line_y1"]), x, float(lifeline["line_y2"]), style="lifeline", stroke="#6f8587", width=1.4, class_name="lifeline"))
    parts.append("</g>")
    parts.append('<g class="executions">')
    for execution in layout.get("executions", ()):
        parts.append(svg_rect(float(execution["x"]), float(execution["y"]), float(execution["width"]), float(execution["height"]), fill="#b9d9d2", stroke="#276b5f", radius=2, class_name="execution"))
    parts.append("</g>")
    parts.append('<g class="messages">')
    for row in layout.get("messages", ()):
        parts.append(_message_line(row))
        label_class = "message-label candidate" if row.get("candidate") else "message-label"
        parts.append(svg_text(float(row["text_x"]), float(row["text_y"]), row["name"], fill="#263238", size=12, anchor="middle", class_name=label_class))
        if row.get("guard"):
            parts.append(svg_text(float(row["text_x"]), float(row["text_y"]) - 16, row["guard"], fill="#8a5a00", size=11, anchor="middle", class_name="message-guard"))
        if row.get("candidate"):
            parts.append(svg_text(float(row["text_x"]), float(row["y"]) + 18, "待确认", fill="#8a5a00", size=10, anchor="middle", class_name="candidate-badge"))
    parts.append("</g>")
    parts.extend(
        [
            '<g class="legend">',
            svg_text(32, height - 26, "实线实心箭头：同步调用", fill="#526568", size=11),
            svg_text(220, height - 26, "虚线开放箭头：返回消息", fill="#526568", size=11),
            svg_text(420, height - 26, "纵向：时间推进", fill="#526568", size=11),
            "</g>",
            "</svg>",
        ]
    )
    return "".join(parts)
