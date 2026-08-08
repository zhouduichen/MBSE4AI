"""Deterministic SVG renderings for semantic MBSE model views."""

from __future__ import annotations

from html import escape

from rflp_lite.application.mbse_exchange import validate_mbse_model


def render_mbse_svg(model: object, view: str = "all") -> str:
    normalized = validate_mbse_model(model)
    if view not in {"all", "use_case", "activity", "sequence"}:
        raise ValueError("unsupported MBSE view")
    sections = []
    if view in {"all", "use_case"}:
        sections.append(("Use Case", [f"{item.get('name', '')} · {', '.join(item.get('actor_ids', ())) }" for item in normalized["use_cases"]]))
    if view in {"all", "activity"}:
        sections.append(("Activity", [f"{item.get('kind', 'action')}: {item.get('name', '')}" for item in normalized["activities"]]))
    if view in {"all", "sequence"}:
        sections.append(("Sequence", [f"{item.get('sequence', '')}. {item.get('from_id', '')} → {item.get('to_id', '')}: {item.get('name', '')}" for item in normalized["messages"]]))
    width = 1120
    height = max(180, 90 + sum(max(1, len(items)) for _, items in sections) * 44)
    parts = [f'<svg class="mbse-svg" viewBox="0 0 {width} {height}" role="img" aria-label="MBSE语义模型" xmlns="http://www.w3.org/2000/svg">', '<rect width="100%" height="100%" rx="16" fill="#0b1416"/>']
    y = 28
    for title, items in sections:
        parts.append(f'<text x="26" y="{y}" fill="#70e1bc" font-size="16" font-weight="800">{escape(title)}</text>')
        y += 28
        for index, item in enumerate(items or ["（暂无候选）"]):
            parts.append(f'<rect x="26" y="{y - 18}" width="1068" height="30" rx="7" fill="#182a2e" stroke="#31504b"/>')
            parts.append(f'<text x="40" y="{y + 2}" fill="#e2eeea" font-size="12">{escape(str(item)[:160])}</text>')
            y += 40
        y += 12
    parts.append("</svg>")
    return "".join(parts)

