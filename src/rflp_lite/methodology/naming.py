"""Stable, solution-neutral labels for generated functional behavior."""

from __future__ import annotations

import re


_SOLUTION_SPECIFIC_TERMS = re.compile(
    r"(?:sensor|芯片|传感器|数据库|database|arduino|raspberry|stm32|型号|part[- ]?number)",
    re.IGNORECASE,
)


def solution_neutral_function_name(requirement, *, prefix: str = "系统能力") -> str:
    """Name a Function without turning a requirement's implementation noun into a part.

    The complete requirement remains in the Function payload for reasoning and
    traceability. Only the display name is normalized so semantic validation
    can keep enforcing solution neutrality, including during fallback recovery.
    The stable ID suffix keeps otherwise similar requirements distinct.
    """

    payload = getattr(requirement, "payload", {})
    meta = getattr(requirement, "meta", None)
    source = str(payload.get("statement") or getattr(meta, "name", ""))
    label = _SOLUTION_SPECIFIC_TERMS.sub("", " ".join(source.split()))
    label = label.strip(" ：:;；,，。.!！?？")
    if not label:
        label = "需求对应能力"
    requirement_id = str(getattr(requirement, "id", ""))
    suffix = requirement_id.rsplit("-", 1)[-1][:8] or "unknown"
    return f"{prefix}：{label[:32]}（{suffix}）"


__all__ = ["solution_neutral_function_name"]
