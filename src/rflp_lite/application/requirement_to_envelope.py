"""Application bridge from reviewed requirements to concept envelopes."""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median
from collections.abc import Mapping, Sequence

from rflp_lite.application.parameter_rules import create_indicator_envelope
from rflp_lite.application.requirement_clause_splitter import RequirementClauseSplitter
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
    envelope: IndicatorEnvelope
    field_provenance: tuple[EnvelopeFieldProvenance, ...]
    diagnostics: tuple[str, ...]


_ALIASES: dict[str, tuple[str, str]] = {
    "最大起飞重量": ("mass_kg", "kg"),
    "起飞重量": ("mass_kg", "kg"),
    "MTOW": ("mass_kg", "kg"),
    "质量": ("mass_kg", "kg"),
    "空机质量": ("mass_kg", "kg"),
    "翼展": ("span_m", "m"),
    "航程": ("range_km", "km"),
    "任务载荷": ("payload_kg", "kg"),
    "载荷": ("payload_kg", "kg"),
    "巡航速度": ("cruise_speed_mps", "m/s"),
    "速度": ("cruise_speed_mps", "m/s"),
    "机翼面积": ("wing_area_m2", "m2"),
    "机身长度": ("fuselage_length_m", "m"),
}
_UNIT_ALIASES = {"千克": "kg", "公斤": "kg", "公里": "km", "米": "m", "秒": "s"}
_UNIT_SCALE = {
    ("km/h", "m/s"): 1 / 3.6,
    ("千米/时", "m/s"): 1 / 3.6,
}


def _number(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise ContractViolation(f"{label} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ContractViolation(f"{label} must be numeric") from exc
    if not math.isfinite(number):
        raise ContractViolation(f"{label} must be finite")
    return number


def _specs(pack: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    return {
        str(item["name"]): item
        for item in pack.get("parameters", ())
        if isinstance(item, Mapping) and isinstance(item.get("name"), str)
    }


def _values(value: object) -> dict[str, object]:
    if isinstance(value, SchemeRecord):
        return dict(value.parameters)
    if isinstance(value, Mapping):
        raw = value.get("parameters", value)
        if isinstance(raw, Mapping):
            return {str(key): item for key, item in raw.items()}
        if isinstance(raw, (list, tuple)):
            return {
                str(item[0]): item[1]
                for item in raw
                if isinstance(item, (list, tuple)) and len(item) == 2
            }
    return {}


def _history_medians(history: Sequence[SchemeRecord | Mapping[str, object]]) -> dict[str, float]:
    by_name: dict[str, list[float]] = {}
    for record in history:
        for name, value in _values(record).items():
            try:
                number = _number(value, f"history parameter {name}")
            except ContractViolation:
                continue
            by_name.setdefault(name, []).append(number)
    return {name: float(median(values)) for name, values in by_name.items() if values}


def _mapping(pack: Mapping[str, object], name: str) -> tuple[str, str] | None:
    raw = pack.get("semantic_mappings", {})
    if isinstance(raw, Mapping):
        item = raw.get(name)
        if isinstance(item, Mapping) and isinstance(item.get("parameter"), str):
            return str(item["parameter"]), str(item.get("unit", ""))
    return _ALIASES.get(name)


def _convert(value: float, source_unit: str, target_unit: str) -> float:
    source = _UNIT_ALIASES.get(source_unit, source_unit)
    target = _UNIT_ALIASES.get(target_unit, target_unit)
    if source == target or not source:
        return value
    scale = _UNIT_SCALE.get((source, target))
    if scale is None:
        raise ContractViolation(f"unsupported unit conversion: {source} -> {target}")
    converted = value * scale
    if not math.isfinite(converted):
        raise ContractViolation("unit conversion produced a non-finite value")
    return converted


def _metric_values(requirement: Mapping[str, object]) -> tuple[dict[str, object], ...]:
    raw = requirement.get("normalized_metrics", ())
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        metrics = tuple(item for item in raw if isinstance(item, Mapping))
        if metrics:
            return tuple(dict(item) for item in metrics)
    statement = str(requirement.get("statement", requirement.get("object", ""))).strip()
    if not statement:
        return ()
    analysis = RequirementClauseSplitter().analyze(statement)
    return tuple(
        {
            "name": metric.name,
            "value": metric.value,
            "unit": metric.unit,
            "operator": metric.operator,
            "source_text": metric.source_text,
        }
        for clause in analysis.clauses
        for metric in clause.normalized_metrics
    )


def _accepted(requirement: Mapping[str, object]) -> bool:
    return str(requirement.get("status", "candidate")).strip().casefold() in {
        "accepted", "approved", "confirmed"
    }


def _bound_for(
    spec: Mapping[str, object], operator: str, value: float
) -> tuple[float, float]:
    declared_min = float(spec.get("minimum", value))
    declared_max = float(spec.get("maximum", value))
    if operator in {"<=", "<"}:
        return declared_min, value
    if operator in {">=", ">"}:
        return value, declared_max
    return value, value


def _merge_bound(
    bounds: dict[str, tuple[float, float]], name: str, pair: tuple[float, float]
) -> None:
    previous = bounds.get(name)
    merged = pair if previous is None else (max(previous[0], pair[0]), min(previous[1], pair[1]))
    if merged[0] > merged[1]:
        raise ContractViolation(f"conflicting requirement bounds for {name}")
    bounds[name] = merged


def build_envelope_from_requirements(
    pack: Mapping[str, object],
    requirements: Sequence[Mapping[str, object]],
    *,
    attributes: Sequence[Mapping[str, object]] = (),
    constraints: Sequence[Mapping[str, object]] = (),
    history: Sequence[SchemeRecord | Mapping[str, object]] = (),
) -> RequirementEnvelopeResult:
    """Build a validated envelope while preserving every source decision."""

    specs = _specs(pack)
    if not specs:
        raise ContractViolation("domain pack has no parameters")
    values: dict[str, object] = {}
    bounds: dict[str, tuple[float, float]] = {}
    source_ids_by_parameter: dict[str, set[str]] = {}
    provenance: dict[str, EnvelopeFieldProvenance] = {}
    diagnostics: list[str] = []

    for requirement in requirements:
        if not isinstance(requirement, Mapping) or not _accepted(requirement):
            continue
        requirement_id = str(requirement.get("id", "")).strip()
        for metric in _metric_values(requirement):
            metric_name = str(metric.get("name", "")).strip()
            mapping = _mapping(pack, metric_name)
            if mapping is None:
                if metric_name in {"通信中断", "通信失联", "失联", "中断"}:
                    diagnostics.append(f"behavior_only:{metric_name}")
                else:
                    diagnostics.append(f"unmapped:{metric_name}")
                continue
            parameter, declared_unit = mapping
            spec = specs.get(parameter)
            if spec is None:
                diagnostics.append(f"unmapped:{parameter}")
                continue
            source_unit = str(metric.get("unit", "") or declared_unit or spec.get("unit", ""))
            target_unit = str(spec.get("unit", ""))
            try:
                number = _convert(_number(metric.get("value"), f"{metric_name}.value"), source_unit, target_unit)
            except ContractViolation as exc:
                diagnostics.append(f"invalid:{metric_name}:{exc}")
                continue
            operator = str(metric.get("operator", "=="))
            if operator in {"<=", "<", ">=", ">", "=="}:
                _merge_bound(bounds, parameter, _bound_for(spec, operator, number))
            else:
                diagnostics.append(f"invalid_operator:{metric_name}:{operator}")
                continue
            values[parameter] = number if operator == "==" else sum(bounds[parameter]) / 2
            source_ids_by_parameter.setdefault(parameter, set()).add(requirement_id)
            provenance[parameter] = EnvelopeFieldProvenance(
                parameter=parameter,
                source_kind="explicit",
                requirement_ids=tuple(sorted(source_ids_by_parameter[parameter])),
                note=f"来自 Requirement {requirement_id}：{metric.get('source_text', metric_name)}",
            )

    # Attributes/constraints are accepted as a compatibility input for callers
    # that already ran the detail extractor. Requirements remain authoritative.
    for attribute in attributes:
        if not isinstance(attribute, Mapping):
            continue
        name = str(attribute.get("name", "")).strip()
        mapping = _mapping(pack, name)
        if mapping is None or mapping[0] in values:
            continue
        value = attribute.get("value")
        if value in (None, ""):
            continue
        parameter, declared_unit = mapping
        spec = specs.get(parameter)
        if spec is None:
            continue
        number = _convert(_number(value, f"{name}.value"), str(attribute.get("unit", declared_unit)), str(spec.get("unit", "")))
        values[parameter] = number
        ids = tuple(str(item) for item in attribute.get("requirement_ids", (attribute.get("requirement_id", ""),)) if str(item).strip())
        source_ids_by_parameter.setdefault(parameter, set()).update(ids)
        provenance[parameter] = EnvelopeFieldProvenance(parameter, "explicit", tuple(sorted(source_ids_by_parameter[parameter])), "来自 RequirementAttribute")

    history_values = _history_medians(history)
    for name, spec in specs.items():
        if name in values:
            continue
        if name in history_values:
            values[name] = history_values[name]
            provenance[name] = EnvelopeFieldProvenance(name, "suggested", (), "历史方案中位数")
        elif "default" in spec:
            values[name] = spec["default"]
            provenance[name] = EnvelopeFieldProvenance(name, "suggested", (), "领域包默认值")
        elif bool(spec.get("required", False)):
            diagnostics.append(f"missing_required:{name}")

    missing_required = [
        name for name, spec in specs.items()
        if bool(spec.get("required", False)) and name not in values
    ]
    if missing_required:
        raise ContractViolation(
            "cannot build indicator envelope; missing required parameters: "
            + ", ".join(sorted(missing_required))
        )

    source_requirement_ids = tuple(
        sorted({
            str(requirement.get("id", "")).strip()
            for requirement in requirements
            if isinstance(requirement, Mapping) and _accepted(requirement) and str(requirement.get("id", "")).strip()
        })
    )
    payload = {
        "status": "draft",
        "source_requirement_ids": source_requirement_ids,
        "parameters": values,
        "bounds": {
            name: {"minimum": pair[0], "maximum": pair[1]}
            for name, pair in sorted(bounds.items())
        },
    }
    envelope = create_indicator_envelope(pack, payload, source_requirement_ids)

    # Pack-derived values are auditable even though they remain outside the
    # fixed envelope parameter tuple used by the layout generator.
    for item in pack.get("derived_parameters", ()):
        if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
            continue
        name = str(item["name"])
        provenance.setdefault(
            name,
            EnvelopeFieldProvenance(name, "derived", source_requirement_ids, f"领域包公式：{item.get('formula', '')}"),
        )
    return RequirementEnvelopeResult(
        envelope=envelope,
        field_provenance=tuple(provenance[name] for name in sorted(provenance)),
        diagnostics=tuple(dict.fromkeys(diagnostics)),
    )


__all__ = [
    "EnvelopeFieldProvenance",
    "RequirementEnvelopeResult",
    "build_envelope_from_requirements",
]
