"""Conservative extraction of reviewable requirement attributes and constraints."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from rflp_lite.domain.requirement_details import RequirementAttribute, RequirementConstraint


_BOUND = re.compile(
    r"(?P<name>[\u4e00-\u9fffA-Za-z_]{2,24})"
    r".{0,8}?(?P<op>不低于|不少于|不超过|不得超过|>=|<=|≥|≤)\s*"
    r"(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>km/h|m/s|mm|m|kg|N|Pa|%|°|套|个|组)?"
)
_OP_VALUE = re.compile(
    r"(?P<op>不低于|不少于|不超过|不得超过|>=|<=|≥|≤)\s*"
    r"(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>km/h|m/s|mm|m|kg|N|Pa|%|°|套|个|组)?"
)
_OPERATORS = {
    "不低于": ">=", "不少于": ">=", "≥": ">=", ">=": ">=",
    "不超过": "<=", "不得超过": "<=", "≤": "<=", "<=": "<=",
}


def _region_text(regions: Mapping[str, object] | Iterable[object], region_ids: tuple[str, ...]) -> str:
    if isinstance(regions, Mapping):
        return " ".join(str(regions.get(region_id, "")) for region_id in region_ids)
    by_id = {
        str(getattr(item, "id", item.get("id", "")) if isinstance(item, Mapping) else getattr(item, "id", "")): item
        for item in regions
    }
    return " ".join(
        str(item.get("text", "") if isinstance(item, Mapping) else getattr(item, "text", ""))
        for item in (by_id.get(region_id) for region_id in region_ids)
        if item is not None
    )


def extract_explicit_details(
    requirements: Iterable[Mapping[str, object]],
    regions: Mapping[str, object] | Iterable[object],
) -> tuple[tuple[RequirementAttribute, ...], tuple[RequirementConstraint, ...]]:
    """Extract only explicit numeric bounds; all results remain candidates."""

    attributes: list[RequirementAttribute] = []
    constraints: list[RequirementConstraint] = []
    for requirement in requirements:
        requirement_id = str(requirement.get("id", "")).strip()
        if not requirement_id:
            continue
        source_ids = tuple(
            str(value).strip()
            for value in (requirement.get("source_region_ids") or (requirement.get("source_region_id", ""),))
            if str(value).strip()
        )
        if not source_ids:
            continue
        text = _region_text(regions, source_ids)
        bound_matches = list(_BOUND.finditer(text))
        if not bound_matches:
            continue
        first = bound_matches[0]
        name = first.group("name").strip()
        for prefix in ("系统", "该", "本"):
            if name.startswith(prefix) and len(name) > len(prefix) + 1:
                name = name[len(prefix):]
        name = re.sub(r"(?:应|需|必须)$", "", name).strip() or first.group("name").strip()
        values = [(first.group("op"), first.group("value"), first.group("unit") or "")]
        values.extend(
            (match.group("op"), match.group("value"), match.group("unit") or "")
            for match in _OP_VALUE.finditer(text, first.end())
        )
        for raw_operator, raw_value, raw_unit in values:
            value = raw_value.strip()
            unit = raw_unit.strip()
            operator = _OPERATORS[raw_operator]
            attributes.append(
                RequirementAttribute.from_fields(
                    requirement_id=requirement_id,
                    name=name,
                    value=value,
                    unit=unit,
                    source_region_ids=source_ids,
                )
            )
            expression = f"{name} {operator} {value}{(' ' + unit) if unit else ''}"
            constraints.append(
                RequirementConstraint.from_fields(
                    requirement_ids=(requirement_id,),
                    constraint_type="performance",
                    expression=expression,
                    explicitness="explicit",
                    source_region_ids=source_ids,
                )
            )
    return tuple(attributes), tuple(constraints)


__all__ = ["extract_explicit_details"]
