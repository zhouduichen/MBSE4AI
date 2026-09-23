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
        (
            ("ms", 1.0),
            ("毫秒", 1.0),
            ("millisecond", 1.0),
            ("milliseconds", 1.0),
            ("s", 1000.0),
            ("秒", 1000.0),
            ("second", 1000.0),
            ("seconds", 1000.0),
        ),
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
        (
            "人工接管", "人工干预", "人工接手", "手动接管",
            "manual override", "human override", "manual intervention", "human intervention",
        ),
        "出现人工接管语义，假设系统需要提供显式的人机接管路径。",
    ),
    (
        "fail_safe_behavior",
        (
            "故障安全", "失效安全", "故障后安全", "安全降级",
            "fail-safe", "fail safe", "safe failure", "safe degradation",
        ),
        "出现故障处置语义，假设系统需要定义故障状态下的安全处置路径。",
    ),
    (
        "fault_tolerance",
        (
            "容错", "冗余", "故障隔离", "失效后继续",
            "fault tolerance", "fault-tolerant", "fault tolerant", "redundancy",
            "fault isolation", "continue after failure",
        ),
        "出现容错语义，假设系统需要具备冗余、隔离或降级机制。",
    ),
    (
        "continuous_operation",
        (
            "持续运行", "连续运行", "全天候",
            "continuous operation", "continuous service", "24/7", "round-the-clock",
        ),
        "出现连续运行语义，假设运行场景包含持续服务或连续任务约束。",
    ),
    (
        "audit_trail",
        (
            "可追溯", "留痕", "审计",
            "audit trail", "audit log", "traceable",
        ),
        "出现审计语义，假设系统需要保留可查询的操作或结果记录。",
    ),
)

# These vocabularies are deliberately small.  They provide useful structure
# for offline intake without pretending to be an open-domain NER model.
_SYSTEM_PROFILE_RULES = (
    ("无人配送机器人", "robot", "无人配送机器人"),
    ("传感器系统", "sensor_system", "传感器系统"),
    ("飞行器", "aircraft", "飞行器"),
    ("无人机", "uav", "无人机"),
    ("车辆", "vehicle", "车辆"),
    ("机器人", "robot", "机器人"),
)
_ENVIRONMENT_RULES = (
    ("校园", "校园"),
    ("室内", "室内"),
    ("室外", "室外"),
    ("海上", "海上"),
    ("空中", "空中"),
    ("高温", "高温"),
    ("低温", "低温"),
)
_MISSION_RULES = (
    ("配送", "配送"),
    ("巡检", "巡检"),
    ("侦察", "侦察"),
    ("作战", "作战"),
    ("维护", "维护"),
)
_STAKEHOLDER_RULES = (
    ("操作员", "actor_operator", "操作员", "任务执行者"),
    ("operator", "actor_operator", "操作员", "任务执行者"),
    ("指挥员", "actor_commander", "指挥员", "任务指挥"),
    ("维护人员", "actor_maintainer", "维护人员", "维护与保障"),
    ("管理员", "actor_administrator", "管理员", "系统管理"),
    ("安全监管方", "actor_safety_regulator", "安全监管方", "安全监管"),
    ("用户", "actor_user", "用户", "任务使用者"),
    ("user", "actor_user", "用户", "任务使用者"),
)
_CONCERN_RULES = (
    ("故障安全", "concern_safety", "安全性", "故障安全语义"),
    ("安全性", "concern_safety", "安全性", "安全性语义"),
    ("可靠性", "concern_reliability", "可靠性", "可靠性语义"),
    ("容错", "concern_reliability", "可靠性", "容错语义"),
    ("冗余", "concern_reliability", "可靠性", "冗余语义"),
    ("持续运行", "concern_reliability", "可靠性", "连续运行语义"),
    ("可维护", "concern_maintainability", "可维护性", "可维护性语义"),
    ("维护", "concern_maintainability", "可维护性", "维护语义"),
    ("性能", "concern_performance", "性能", "性能语义"),
    ("时延", "concern_performance", "性能", "时延语义"),
    ("功耗", "concern_performance", "性能", "功耗语义"),
    ("续航", "concern_performance", "性能", "续航语义"),
    ("互操作", "concern_interoperability", "互操作性", "互操作语义"),
    ("接口", "concern_interoperability", "互操作性", "接口语义"),
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


def infer_system_profile(
    text: str, source_refs: Sequence[str] = ()
) -> Mapping[str, object]:
    """Capture a bounded system profile from known platform/domain phrases."""

    normalized = str(text or "").casefold()
    refs = list(dict.fromkeys(str(item).strip() for item in source_refs if str(item).strip()))
    profile = next(
        (
            (code, label)
            for phrase, code, label in sorted(_SYSTEM_PROFILE_RULES, key=lambda item: len(item[0]), reverse=True)
            if phrase.casefold() in normalized
        ),
        ("generic_system", "目标系统"),
    )
    code, label = profile
    attributes = {
        "platform_type": code,
        "platform_label": label,
        "capture_source": "derived",
        "rule_id": f"system-profile:{code}",
        "confidence": 0.45,
    }
    environments = [
        label
        for phrase, label in _ENVIRONMENT_RULES
        if phrase.casefold() in normalized
    ]
    mission_domains = [
        label
        for phrase, label in _MISSION_RULES
        if phrase.casefold() in normalized
    ]
    if environments:
        attributes["operating_environment"] = list(dict.fromkeys(environments))
    if mission_domains:
        attributes["mission_domain"] = list(dict.fromkeys(mission_domains))
    return {"name": label, "attributes": attributes, "source_refs": refs}


def infer_requirement_entities(
    text: str, source_refs: Sequence[str] = ()
) -> tuple[Mapping[str, object], ...]:
    """Capture known stakeholders and concerns as reviewable derived entities."""

    normalized = str(text or "").casefold()
    refs = list(dict.fromkeys(str(item).strip() for item in source_refs if str(item).strip()))
    result: list[Mapping[str, object]] = []
    seen: set[str] = set()
    for phrase, local_ref, name, role in _STAKEHOLDER_RULES:
        if local_ref in seen or phrase.casefold() not in normalized:
            continue
        seen.add(local_ref)
        result.append({
            "local_ref": local_ref,
            "kind": "stakeholder",
            "name": name,
            "attributes": {
                "role": role,
                "capture_source": "derived",
                "rule_id": f"stakeholder:{local_ref}",
            },
            "source_refs": refs,
            "confidence": 0.45,
        })
    for phrase, local_ref, name, matched_as in _CONCERN_RULES:
        if local_ref in seen or phrase.casefold() not in normalized:
            continue
        seen.add(local_ref)
        result.append({
            "local_ref": local_ref,
            "kind": "concern",
            "name": name,
            "attributes": {
                "topic": name,
                "matched_phrase": matched_as,
                "capture_source": "derived",
                "rule_id": f"concern:{local_ref}",
            },
            "source_refs": refs,
            "confidence": 0.45,
        })
    return tuple(result)
