"""Build a reviewable concept-design input proposal from ModelGraph requirements."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from rflp_lite.application.requirement_scope import root_requirement_ids
from rflp_lite.domain.model import ModelGraph


_NUMBER = r"(?P<value>\d+(?:\.\d+)?)"
_MAX_PHRASES = ("不得超过", "不超过", "最多", "上限", "不高于", "不大于", "<=", "≤")
_MIN_PHRASES = ("不得少于", "不少于", "至少", "下限", "不低于", "不小于", ">=", "≥")
_MAX = rf"(?:{'|'.join(map(re.escape, _MAX_PHRASES))})"
_MIN = rf"(?:{'|'.join(map(re.escape, _MIN_PHRASES))})"
_MAX_OPERATORS = frozenset(item.casefold() for item in _MAX_PHRASES)
_MIN_OPERATORS = frozenset(item.casefold() for item in _MIN_PHRASES)
_UNITS = {
    "kg": ("kg", "千克", "公斤"),
    "m": ("m", "米"),
    "m2": ("m2", "平方米", "平方"),
    "m3": ("m3", "立方米"),
    "m/s": ("m/s", "米/秒"),
    "Pa": ("Pa", "帕"),
}
_SCALES = {
    ("千克", "kg"): 1.0, ("公斤", "kg"): 1.0,
    ("米", "m"): 1.0, ("平方米", "m2"): 1.0, ("平方", "m2"): 1.0,
    ("立方米", "m3"): 1.0, ("米/秒", "m/s"): 1.0, ("帕", "Pa"): 1.0,
}


def _aliases(pack: Mapping[str, object], parameter: str) -> tuple[str, ...]:
    values = {parameter}
    mappings = pack.get("requirement_mappings", {})
    if isinstance(mappings, Mapping):
        for source, raw in mappings.items():
            mapping = raw if isinstance(raw, Mapping) else {"parameter": raw}
            if str(mapping.get("parameter", "")) != parameter:
                continue
            values.add(str(source))
            values.update(str(item) for item in mapping.get("aliases", ()) or ())
    return tuple(sorted((item for item in values if item), key=len, reverse=True))


def _convert(value: float, unit: str, target: str) -> float:
    if unit == target:
        return value
    if unit == "g" and target == "kg":
        return value / 1000.0
    if unit == "cm" and target == "m":
        return value / 100.0
    if unit == "mm" and target == "m":
        return value / 1000.0
    return value * _SCALES.get((unit, target), 1.0)


def _normalize_operator(value: object) -> str:
    operator = str(value or "").strip().casefold()
    if operator in _MAX_OPERATORS:
        return "max"
    if operator in _MIN_OPERATORS:
        return "min"
    return "exact"


def _statement_values(statement: str, aliases: tuple[str, ...], unit: str) -> tuple[tuple[str, float], ...]:
    unit_values = _UNITS.get(unit, (unit,)) if unit != "1" else (r"",)
    alias_pattern = "|".join(re.escape(item) for item in aliases)
    unit_pattern = "|".join(re.escape(item) for item in unit_values if item)
    comparator = rf"(?P<operator>{_MAX}|{_MIN}|为|是|约为|约)?"
    suffix = rf"\s*(?P<unit>{unit_pattern})" if unit_pattern else ""
    pattern = re.compile(rf"(?:{alias_pattern})\s*{comparator}\s*{_NUMBER}{suffix}", re.IGNORECASE)
    values: list[tuple[str, float]] = []
    for match in pattern.finditer(statement):
        raw_unit = str(match.groupdict().get("unit") or unit)
        values.append((_normalize_operator(match.groupdict().get("operator")), _convert(float(match["value"]), raw_unit, unit)))
    return tuple(values)


def _constraint_values(requirement: object, parameter: str) -> tuple[tuple[str, float], ...]:
    payload = getattr(requirement, "payload", {})
    constraints = payload.get("constraints", {}) if isinstance(payload, Mapping) else {}
    if not isinstance(constraints, Mapping):
        return ()
    values: list[tuple[str, float]] = []
    for operator, key in (("min", f"min_{parameter}"), ("max", f"max_{parameter}"), ("exact", parameter)):
        value = constraints.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values.append((operator, float(value)))
    return tuple(values)


def suggest_indicator_envelope(graph: ModelGraph, pack: Mapping[str, object]) -> Mapping[str, object]:
    """Return an explicit-input proposal without guessing missing engineering data."""

    source_ids = root_requirement_ids(graph)
    requirements = [item for item in graph.entities if item.id in source_ids]
    specs = pack.get("parameters", ())
    parameters: dict[str, float] = {}
    bounds: dict[str, dict[str, float]] = {}
    evidence: list[dict[str, Any]] = []
    for spec in specs if isinstance(specs, (list, tuple)) else ():
        if not isinstance(spec, Mapping):
            continue
        parameter = str(spec.get("name", ""))
        if not parameter:
            continue
        unit = str(spec.get("unit", "1"))
        for requirement in requirements:
            values = _constraint_values(requirement, parameter)
            if not values:
                values = _statement_values(
                    str(requirement.payload.get("statement", requirement.meta.name)),
                    _aliases(pack, parameter),
                    unit,
                )
            for operator, value in values:
                if operator == "exact":
                    parameters[parameter] = value
                else:
                    bounds.setdefault(parameter, {})["minimum" if operator == "min" else "maximum"] = value
                evidence.append({
                    "parameter": parameter,
                    "requirement_id": requirement.id,
                    "operator": operator,
                    "value": value,
                    "unit": unit,
                    "statement": str(requirement.payload.get("statement", requirement.meta.name)),
                })
        range_value = bounds.get(parameter, {})
        if parameter not in parameters and {"minimum", "maximum"} <= set(range_value):
            parameters[parameter] = (range_value["minimum"] + range_value["maximum"]) / 2.0
    required = {
        str(item.get("name"))
        for item in specs if isinstance(item, Mapping) and item.get("required")
    } if isinstance(specs, (list, tuple)) else set()
    missing = sorted(required - set(parameters))
    envelope = {
        "schema_version": int(pack.get("schema_version", 1)),
        "object_type": str(pack.get("object_type", "layout")),
        "status": "draft",
        "source_requirement_ids": list(source_ids),
        "parameters": dict(sorted(parameters.items())),
        "bounds": dict(sorted(bounds.items())),
    }
    return {
        "status": "ready" if not missing else "needs_input",
        "source_requirement_ids": list(source_ids),
        "envelope": envelope,
        "inferred_parameters": dict(sorted(parameters.items())),
        "inferred_bounds": dict(sorted(bounds.items())),
        "missing_parameters": missing,
        "evidence": evidence,
        "diagnostics": [
            "指标值仅来自 ModelGraph 中的显式需求约束或参数化表述；缺失项不会自动猜测。"
        ],
    }


__all__ = ["suggest_indicator_envelope"]
