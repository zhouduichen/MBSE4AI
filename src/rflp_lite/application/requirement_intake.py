"""Normalize sentence-sized requirement inputs without rewriting their meaning."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence


_SEPARATOR = re.compile(r"(?:\r?\n+|[；;。！？!?]+|(?<=[.!?])\s+(?=[A-Z]))")
_LIST_PREFIX = re.compile(
    r"^\s*(?:(?:[-*•])\s*|\d+[.)、]\s*|[（(][一二三四五六七八九十\d]+[）)]\s*)"
)
_NUMBER = r"(?P<value>\d+(?:\.\d+)?)"
_OPERATORS = (
    r"(?P<operator>不得超过|不得大于|不得高于|不得少于|不得低于|不超过|不大于|不高于|最多|小于等于|不少于|不小于|不低于|至少|大于等于|"
    r"no more than|no less than|at most|at least|<=|>=|≤|≥|<|>)"
)
_METRICS = (
    (
        "power_w",
        ("功耗", "power consumption", "power"),
        (("kw", 1000.0), ("千瓦", 1000.0), ("w", 1.0), ("瓦", 1.0)),
    ),
    (
        "mass_kg",
        ("质量", "重量", "mass", "weight"),
        (("kg", 1.0), ("千克", 1.0), ("公斤", 1.0), ("g", 0.001), ("克", 0.001)),
    ),
    (
        "latency_ms",
        ("时延", "延迟", "响应时间", "latency", "response time"),
        (("ms", 1.0), ("毫秒", 1.0), ("s", 1000.0), ("秒", 1000.0)),
    ),
    (
        "bandwidth_mbps",
        ("带宽", "bandwidth"),
        (("gbps", 1000.0), ("gb/s", 1000.0), ("兆比特/秒", 1.0), ("mbps", 1.0)),
    ),
    (
        "cost",
        ("成本", "费用", "cost"),
        (("元", 1.0), ("人民币", 1.0), ("cny", 1.0), ("¥", 1.0), ("￥", 1.0)),
    ),
    (
        "endurance_h",
        ("续航", "持续运行时间", "运行时间", "endurance", "runtime", "operating time"),
        (
            ("小时", 1.0),
            ("hours", 1.0),
            ("hour", 1.0),
            ("h", 1.0),
            ("分钟", 1 / 60.0),
            ("minutes", 1 / 60.0),
            ("minute", 1 / 60.0),
            ("min", 1 / 60.0),
        ),
    ),
)
_MAX_OPERATORS = {
    "不得超过", "不得大于", "不得高于", "不超过", "不大于", "不高于", "最多", "小于等于",
    "no more than", "at most", "<=", "≤", "<",
}

_IMPLICIT_RULES = (
    (
        "human_override",
        ("人工接管", "人工干预", "人工接手", "手动接管"),
        "出现人工接管语义，假设系统需要提供显式的人机接管路径。",
    ),
    (
        "fail_safe_behavior",
        ("故障安全", "失效安全", "故障后安全", "安全降级"),
        "出现故障处置语义，假设系统需要定义故障状态下的安全处置路径。",
    ),
    (
        "fault_tolerance",
        ("容错", "冗余", "故障隔离", "失效后继续"),
        "出现容错语义，假设系统需要具备冗余、隔离或降级机制。",
    ),
    (
        "continuous_operation",
        ("持续运行", "连续运行", "全天候"),
        "出现连续运行语义，假设运行场景包含持续服务或连续任务约束。",
    ),
    (
        "audit_trail",
        ("可追溯", "留痕", "审计"),
        "出现审计语义，假设系统需要保留可查询的操作或结果记录。",
    ),
)


def split_requirement_statements(text: str) -> tuple[str, ...]:
    """Return ordered, normalized requirement-sized statements from ``text``."""

    values: list[str] = []
    seen: set[str] = set()
    for raw in _SEPARATOR.split(str(text or "")):
        value = _LIST_PREFIX.sub("", raw)
        value = " ".join(value.split()).strip().rstrip("。；;！？!?.")
        if value and value not in seen:
            seen.add(value)
            values.append(value)
    return tuple(values)


def extract_requirement_constraints(statement: str) -> Mapping[str, object]:
    """Extract explicit, unit-aware engineering bounds from one statement.

    This is intentionally a bounded enrichment step rather than a general
    language interpretation pass.  A constraint needs a known metric,
    comparator, number, and unit, except that an explicitly compared cost may
    omit its currency unit.
    """

    text = str(statement or "").translate(str.maketrans("０１２３４５６７８９．", "0123456789."))
    candidates = []
    for field, aliases, units in _METRICS:
        alias_pattern = "|".join(
            re.escape(alias) for alias in sorted(aliases, key=len, reverse=True)
        )
        unit_pattern = "|".join(
            re.escape(unit) for unit, _ in sorted(units, key=lambda item: len(item[0]), reverse=True)
        )
        connector = r"(?:must\s+be|should\s+be|shall\s+be|has\s+to\s+be|needs\s+to\s+be|is|are)?"
        unit_suffix = (
            rf"\s*(?P<unit>{unit_pattern})(?![A-Za-z])"
            if field != "cost"
            else rf"(?:\s*(?P<unit>{unit_pattern})(?![A-Za-z]))?"
        )
        pattern = re.compile(
            rf"(?<![A-Za-z])(?P<metric>{alias_pattern})(?![A-Za-z])\s*"
            rf"{connector}\s*{_OPERATORS}\s*{_NUMBER}{unit_suffix}",
            re.IGNORECASE,
        )
        factors = {unit.casefold(): factor for unit, factor in units}
        for match in pattern.finditer(text):
            operator = match.group("operator").casefold()
            direction = "max" if operator in _MAX_OPERATORS else "min"
            unit = match.group("unit")
            factor = factors.get(unit.casefold(), 1.0) if unit else 1.0
            value = float(match.group("value")) * factor
            candidates.append(
                {
                    "key": f"{direction}_{field}",
                    "field": field,
                    "operator": direction,
                    "value": value,
                    "unit": unit or "",
                    "text": match.group(0),
                    "start": match.start(),
                }
            )

    selected = {}
    for candidate in candidates:
        key = candidate["key"]
        current = selected.get(key)
        if current is None or (
            candidate["operator"] == "max" and candidate["value"] < current["value"]
        ) or (
            candidate["operator"] == "min" and candidate["value"] > current["value"]
        ):
            selected[key] = candidate
    if not selected:
        return {}

    ordered = sorted(selected.values(), key=lambda item: (item["start"], item["key"]))
    return {
        "constraints": {item["key"]: item["value"] for item in ordered},
        "constraint_provenance": [
            {
                key: item[key]
                for key in ("field", "operator", "value", "unit", "text")
            }
            for item in ordered
        ],
    }


def infer_requirement_constraints(
    statement: str, source_refs: Sequence[str] = ()
) -> tuple[Mapping[str, object], ...]:
    """Infer only bounded semantic flags, preserving their review status.

    This is deliberately not a numerical or open-domain NLP guesser.  The
    returned boolean constraints express a semantic candidate derived from a
    phrase family; callers must keep the low confidence and assumption.
    """

    text = str(statement or "").casefold()
    refs = list(dict.fromkeys(str(item).strip() for item in source_refs if str(item).strip()))
    result: list[Mapping[str, object]] = []
    for field, phrases, assumption in _IMPLICIT_RULES:
        if any(phrase.casefold() in text for phrase in phrases):
            result.append({
                "field": field,
                "operator": "eq",
                "value": 1.0,
                "unit": "boolean",
                "source": "derived",
                "source_refs": refs,
                "confidence": 0.35,
                "assumption": assumption,
            })
    return tuple(result)
