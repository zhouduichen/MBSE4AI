"""Map reviewed requirements into a typed indicator envelope.

This module is the narrow bridge between customer language and the existing
domain-pack parameter rules.  Numeric values remain rule-derived and every
field records whether it came from an explicit requirement, a safe formula,
or a historical suggestion.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from rflp_lite.application.parameter_rules import create_indicator_envelope, evaluate_formula
from rflp_lite.domain.concept_design import IndicatorEnvelope, SchemeRecord
from rflp_lite.domain.errors import ContractViolation


@dataclass(frozen=True, slots=True)
class EnvelopeFieldProvenance:
    parameter: str
    source_kind: str
    requirement_ids: tuple[str, ...]
    note: str


@dataclass(frozen=True, slots=True)
class RequirementEnvelopeResult:
    envelope: IndicatorEnvelope | None
    field_provenance: tuple[EnvelopeFieldProvenance, ...]
    diagnostics: tuple[str, ...]


_UNIT_SCALE = {
    ("mm", "m"): 0.001,
    ("cm", "m"): 0.01,
    ("g", "kg"): 0.001,
    ("km/h", "m/s"): 1 / 3.6,
    ("秒", "s"): 1.0,
    ("米", "m"): 1.0,
    ("千克", "kg"): 1.0,
}
_FALLBACK_MAPPINGS = {
    "最大起飞重量": "mass_kg",
    "最大起飞质量": "mass_kg",
    "空机质量": "mass_kg",
    "翼展": "span_m",
    "航程": "range_km",
    "任务载荷": "payload_kg",
    "载荷": "payload_kg",
    "巡航速度": "cruise_speed_mps",
    "机翼面积": "wing_area_m2",
    "机身长度": "fuselage_length_m",
    "截面模量": "section_modulus_m3",
    "剖面模量": "section_modulus_m3",
    "许用应力": "allowable_stress_pa",
    "允许应力": "allowable_stress_pa",
    "重心位置": "cg_x_m",
    "重心": "cg_x_m",
}
_OPERATOR_PATTERN = re.compile(
    r"(?P<name>[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9 _/\-]{1,32}?)\s*"
    r"(?P<operator>不超过|不得大于|不高于|不低于|不少于|至少|以上|≤|≥|<=|>=|==|<|>)\s*"
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>km/h|m/s|kg|km|mm|m2|m3|Pa|m|s|秒|米|千克)?",
    re.IGNORECASE,
)
_OPS = {
    "不超过": "<=", "不得大于": "<=", "不高于": "<=", "≤": "<=", "<=": "<=",
    "不低于": ">=", "不少于": ">=", "至少": ">=", "以上": ">=", "≥": ">=", ">=": ">=",
    "==": "==", "<": "<", ">": ">",
}


def _specs(pack: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    return {
        str(item["name"]): item
        for item in pack.get("parameters", ())
        if isinstance(item, Mapping) and isinstance(item.get("name"), str)
    }


def _text(value: object) -> str:
    return str(value or "").strip()


def _unique(values: Sequence[object]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        clean = _text(value)
        if clean and clean not in result:
            result.append(clean)
    return tuple(result)


def _number(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("value must be numeric")
    return float(value)


def _convert(value: object, source_unit: str, target_unit: str) -> float:
    number = _number(value)
    if source_unit == target_unit or not source_unit:
        return number
    try:
        return number * _UNIT_SCALE[(source_unit, target_unit)]
    except KeyError as exc:
        raise ValueError(f"unsupported unit conversion: {source_unit} -> {target_unit}") from exc


def _mapping_table(pack: Mapping[str, object]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    raw = pack.get("requirement_mappings", pack.get("semantic_mappings", {}))
    if isinstance(raw, Mapping):
        for name, item in raw.items():
            if isinstance(item, str):
                result[str(name)] = {"parameter": item}
            elif isinstance(item, Mapping):
                result[str(name)] = dict(item)
    for name, parameter in _FALLBACK_MAPPINGS.items():
        result.setdefault(name, {"parameter": parameter, "fallback": True})
    return result


def _resolve_mapping(pack: Mapping[str, object], name: str) -> tuple[str, dict[str, object]] | None:
    table = _mapping_table(pack)
    clean = re.sub(r"\s+", "", name)
    for source, config in table.items():
        aliases = config.get("aliases", ())
        names = (source, *aliases) if isinstance(aliases, (tuple, list)) else (source,)
        if any(re.sub(r"\s+", "", str(alias)) == clean for alias in names):
            target = str(config.get("parameter", "")).strip()
            return target, config
    return None


def _allowed_requirements(requirements: Sequence[Mapping[str, object]]) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for requirement in requirements:
        identifier = _text(requirement.get("id"))
        if not identifier or _text(requirement.get("status", "accepted")) == "rejected":
            continue
        result[identifier] = requirement
    return result


def _embedded_attributes(requirement: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    raw = requirement.get("attributes", requirement.get("details", ()))
    if isinstance(raw, Mapping):
        raw = (raw,)
    if not isinstance(raw, (tuple, list)):
        return ()
    return tuple(item for item in raw if isinstance(item, Mapping))


def _constraint_metrics(requirement_id: str, expression: str) -> tuple[tuple[str, float, str, str, str], ...]:
    result = []
    for match in _OPERATOR_PATTERN.finditer(expression):
        unit = {"秒": "s", "米": "m", "千克": "kg", "pa": "Pa"}.get(
            (match.group("unit") or "").casefold(), match.group("unit") or ""
        )
        result.append((match.group("name").strip(), float(match.group("value")), unit, _OPS[match.group("operator")], requirement_id))
    return tuple(result)


def _history_parameters(history: Sequence[SchemeRecord | Mapping[str, object]]) -> dict[str, object]:
    records = sorted(history, key=lambda item: str(item.id if isinstance(item, SchemeRecord) else item.get("id", "")))
    for record in records:
        raw = record.parameters if isinstance(record, SchemeRecord) else record.get("parameters", ())
        if isinstance(raw, Mapping):
            values = dict(raw)
        else:
            values = {
                str(item[0]): item[1]
                for item in raw
                if isinstance(item, (tuple, list)) and len(item) == 2
            }
        if values:
            return values
    return {}


def _bound(value: float, operator: str, spec: Mapping[str, object]) -> tuple[float | None, float | None]:
    if operator in {">=", ">"}:
        return value, None
    elif operator in {"<=", "<"}:
        return None, value
    return None, None


def build_envelope_from_requirements(
    pack: Mapping[str, object],
    requirements: Sequence[Mapping[str, object]],
    *,
    attributes: Sequence[Mapping[str, object]] = (),
    constraints: Sequence[Mapping[str, object]] = (),
    history: Sequence[SchemeRecord | Mapping[str, object]] = (),
    llm_suggestions: Sequence[Mapping[str, object]] = (),
    provisional: bool = False,
) -> RequirementEnvelopeResult:
    """Build an envelope without inventing values for unmapped requirements."""

    specs = _specs(pack)
    allowed = _allowed_requirements(requirements)
    diagnostics: list[str] = []
    explicit: dict[str, dict[str, object]] = {}
    provenance: dict[str, EnvelopeFieldProvenance] = {}

    def record(name: str, raw_value: object, unit: str, operator: str, requirement_ids: tuple[str, ...], note: str) -> None:
        resolved = _resolve_mapping(pack, name)
        if resolved is None:
            diagnostics.append(f"需求指标缺少领域包映射：{name}")
            return
        parameter, mapping = resolved
        if parameter not in specs:
            diagnostics.append(f"领域包缺少目标参数：{name} → {parameter}")
            return
        target_unit = str(specs[parameter].get("unit", ""))
        try:
            value = _convert(raw_value, unit, str(mapping.get("unit", target_unit)))
            value = _convert(value, str(mapping.get("unit", target_unit)), target_unit)
        except (TypeError, ValueError) as exc:
            diagnostics.append(f"{name} 无法映射到 {parameter}：{exc}")
            return
        item = explicit.setdefault(parameter, {"values": [], "bounds": [], "requirement_ids": []})
        item["values"].append((value, operator))
        item["requirement_ids"].extend(requirement_ids)
        previous = provenance.get(parameter)
        provenance[parameter] = EnvelopeFieldProvenance(
            parameter,
            "explicit",
            _unique(item["requirement_ids"]),
            note if previous is None else f"{previous.note}；{note}",
        )

    for requirement_id, requirement in allowed.items():
        source_ids = (requirement_id,)
        for attribute in _embedded_attributes(requirement):
            name = _text(attribute.get("name"))
            unit = _text(attribute.get("unit"))
            for key, operator in (("value", "=="), ("minimum", ">="), ("maximum", "<=")):
                raw_value = attribute.get(key)
                if raw_value not in (None, ""):
                    record(name, raw_value, unit, operator, source_ids, f"Requirement {requirement_id} attribute {name}")
        statement = _text(requirement.get("statement", requirement.get("text", "")))
        for name, value, unit, operator, source in _constraint_metrics(requirement_id, statement):
            record(name, value, unit, operator, (source,), f"Requirement {requirement_id} statement")

    for attribute in attributes:
        requirement_id = _text(attribute.get("requirement_id"))
        if requirement_id and requirement_id not in allowed:
            continue
        name = _text(attribute.get("name"))
        source_ids = _unique(attribute.get("source_requirement_ids", (requirement_id,)))
        for key, operator in (("value", "=="), ("minimum", ">="), ("maximum", "<=")):
            raw_value = attribute.get(key)
            if raw_value not in (None, ""):
                record(name, raw_value, _text(attribute.get("unit")), operator, source_ids, f"explicit attribute {name}")

    for constraint in constraints:
        requirement_ids = _unique(constraint.get("requirement_ids", ()))
        if requirement_ids and any(item not in allowed for item in requirement_ids):
            continue
        expression = _text(constraint.get("expression"))
        for name, value, unit, operator, _source in _constraint_metrics(requirement_ids[0] if requirement_ids else "", expression):
            record(name, value, unit, operator, requirement_ids, f"explicit constraint {expression}")

    values: dict[str, object] = {}
    bounds: dict[str, dict[str, float]] = {}
    for parameter, item in explicit.items():
        spec = specs[parameter]
        observations = item["values"]
        lower: float | None = None
        upper: float | None = None
        equality: float | None = None
        for value, operator in observations:
            lo, hi = _bound(float(value), str(operator), spec)
            lower = lo if lo is not None and (lower is None or lo > lower) else lower
            upper = hi if hi is not None and (upper is None or hi < upper) else upper
            if operator == "==":
                equality = float(value)
        if lower is not None or upper is not None:
            bounds[parameter] = {
                "minimum": lower if lower is not None else float(spec.get("minimum", equality or 0.0)),
                "maximum": upper if upper is not None else float(spec.get("maximum", equality or 0.0)),
            }
        values[parameter] = equality if equality is not None else (
            (lower + upper) / 2 if lower is not None and upper is not None else lower if lower is not None else upper
        )

    for suggestion in llm_suggestions:
        if not isinstance(suggestion, Mapping):
            continue
        source_name = _text(suggestion.get("name", suggestion.get("parameter", "")))
        resolved = _resolve_mapping(pack, source_name) if source_name not in specs else (source_name, {})
        if resolved is None:
            diagnostics.append(f"LLM 建议参数无法映射到领域包：{source_name}")
            continue
        parameter, mapping = resolved
        if parameter in values or parameter in provenance or parameter not in specs:
            continue
        raw_value = suggestion.get("value")
        if raw_value in (None, ""):
            continue
        target_unit = _text(specs[parameter].get("unit"))
        source_unit = _text(suggestion.get("unit") or mapping.get("unit"))
        try:
            value = _convert(raw_value, source_unit, target_unit)
            minimum = specs[parameter].get("minimum")
            maximum = specs[parameter].get("maximum")
            if minimum is not None and value < float(minimum):
                raise ValueError(f"below declared minimum {minimum}")
            if maximum is not None and value > float(maximum):
                raise ValueError(f"above declared maximum {maximum}")
        except (TypeError, ValueError) as exc:
            diagnostics.append(f"LLM 建议参数 {parameter} 无效：{exc}")
            continue
        values[parameter] = value
        reason = _text(suggestion.get("reason")) or "LLM 基于设计意图给出的初始估计"
        provenance[parameter] = EnvelopeFieldProvenance(
            parameter,
            "suggested_llm",
            _unique(suggestion.get("requirement_ids", ())),
            f"{reason}；producer=llm",
        )

    history_values = _history_parameters(history)
    for parameter, spec in specs.items():
        if parameter in values or parameter in {item.parameter for item in provenance.values()}:
            continue
        if parameter in history_values:
            try:
                values[parameter] = _convert(history_values[parameter], "", str(spec.get("unit", "")))
            except (TypeError, ValueError):
                continue
            provenance[parameter] = EnvelopeFieldProvenance(parameter, "suggested", (), f"历史方案建议：{parameter}")

    derived = pack.get("requirement_derivations", {})
    if isinstance(derived, Mapping):
        for parameter, raw_formula in derived.items():
            formula = raw_formula.get("formula") if isinstance(raw_formula, Mapping) else raw_formula
            if parameter in values or parameter not in specs or not isinstance(formula, str):
                continue
            names = set(re.findall(r"\b[A-Za-z_]\w*\b", formula))
            if not names.issubset(values):
                continue
            try:
                values[parameter] = evaluate_formula(formula, values)
            except ContractViolation as exc:
                diagnostics.append(f"派生参数 {parameter} 无法计算：{exc}")
                continue
            source_ids = tuple(
                source
                for dependency in sorted(names)
                for source in provenance.get(dependency, EnvelopeFieldProvenance(dependency, "derived", (), "" )).requirement_ids
            )
            provenance[parameter] = EnvelopeFieldProvenance(parameter, "derived", _unique(source_ids), f"公式：{formula}")

    missing = tuple(
        name for name, spec in specs.items()
        if bool(spec.get("required")) and name not in values and spec.get("default") is None
    )
    diagnostics.extend(f"领域包缺少必需参数：{name}" for name in missing)
    if provisional and missing:
        unresolved: list[str] = []
        for name in missing:
            spec = specs[name]
            default = spec.get("default")
            minimum = spec.get("minimum")
            maximum = spec.get("maximum")
            if default is not None:
                value = default
            elif minimum is not None and maximum is not None:
                try:
                    value = (float(minimum) + float(maximum)) / 2
                except (TypeError, ValueError):
                    unresolved.append(name)
                    continue
            else:
                unresolved.append(name)
                continue
            values[name] = value
            provenance[name] = EnvelopeFieldProvenance(
                name,
                "suggested_default",
                (),
                "领域包声明范围/默认值生成的临时初值",
            )
        missing = tuple(unresolved)
    if missing:
        return RequirementEnvelopeResult(None, tuple(provenance.values()), tuple(dict.fromkeys(diagnostics)))

    payload: dict[str, object] = {
        "status": "candidate" if provisional else "approved",
        "parameters": values,
        "source_requirement_ids": _unique(
            source for item in provenance.values() if item.source_kind == "explicit" for source in item.requirement_ids
        ),
        "bounds": bounds,
    }
    try:
        envelope = create_indicator_envelope(pack, payload, tuple(payload["source_requirement_ids"]))
    except ContractViolation as exc:
        diagnostics.append(f"指标包络无法生成：{exc}")
        return RequirementEnvelopeResult(None, tuple(provenance.values()), tuple(dict.fromkeys(diagnostics)))
    return RequirementEnvelopeResult(envelope, tuple(provenance.values()), tuple(dict.fromkeys(diagnostics)))


__all__ = [
    "EnvelopeFieldProvenance",
    "RequirementEnvelopeResult",
    "build_envelope_from_requirements",
]
