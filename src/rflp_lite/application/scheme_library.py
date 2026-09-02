"""Map historical scheme rows into the fixed core :class:`SchemeRecord`."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.concept_design import SchemeRecord


@dataclass(frozen=True, slots=True)
class SchemeImportResult:
    records: tuple[SchemeRecord, ...]
    rejected: tuple[dict[str, object], ...]
    skipped: tuple[str, ...] = ()


_UNIT_SCALE = {
    ("mm", "m"): 0.001,
    ("cm", "m"): 0.01,
    ("g", "kg"): 0.001,
    ("kPa", "Pa"): 1000.0,
    ("km/h", "m/s"): 1 / 3.6,
}


def _number(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    if isinstance(value, str):
        value = value.strip()
        if not value:
            raise ValueError(f"{label} is empty")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def _parse_boolean(value: object, label: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "yes", "y", "1", "是"}:
            return True
        if normalized in {"false", "no", "n", "0", "否"}:
            return False
    raise ValueError(f"{label} must be boolean")


def _parse_value(
    value: object,
    specification: Mapping[str, object],
    mapping: Mapping[str, object],
    label: str,
) -> object:
    # A structured value is convenient for JSON sources that include an
    # explicit unit.  CSV remains a scalar and can use the mapping's
    # source_unit declaration.
    supplied_unit: str | None = None
    if isinstance(value, dict) and "value" in value:
        supplied_unit = value.get("unit") if isinstance(value.get("unit"), str) else None
        value = value["value"]
    declared_type = specification.get("type")
    if declared_type == "number":
        parsed: object = _number(value, label)
        source_unit = supplied_unit or mapping.get("source_unit")
        target_unit = specification.get("unit")
        if source_unit is not None and not isinstance(source_unit, str):
            raise ValueError(f"{label} source_unit must be a string")
        if target_unit is not None and not isinstance(target_unit, str):
            raise ValueError(f"{label} unit must be a string")
        if source_unit and target_unit and source_unit != target_unit:
            try:
                parsed = float(parsed) * _UNIT_SCALE[(source_unit, target_unit)]
            except KeyError as exc:
                raise ValueError(f"unsupported unit conversion: {source_unit} -> {target_unit}") from exc
        if "scale" in mapping:
            parsed = float(parsed) * _number(mapping["scale"], f"{label} scale")
        if not math.isfinite(float(parsed)):
            raise ValueError(f"{label} must be finite")
        return float(parsed)
    if declared_type == "boolean":
        return _parse_boolean(value, label)
    if declared_type == "string":
        if isinstance(value, (dict, list, tuple, set)):
            raise ValueError(f"{label} must be a string")
        return str(value)
    raise ValueError(f"{label} has unsupported declared type")


def _parameter_specs(pack: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    values = pack.get("parameters", ())
    return {
        str(item["name"]): item
        for item in values
        if isinstance(item, Mapping) and isinstance(item.get("name"), str)
    }


def _rejection(row_number: int, source: str, code: str, message: str) -> dict[str, object]:
    return {"row": row_number, "source": source, "code": code, "message": message}


def _check_bounds(value: object, specification: Mapping[str, object], target: str) -> None:
    if specification.get("type") != "number":
        return
    numeric = float(value)
    minimum = specification.get("minimum")
    maximum = specification.get("maximum")
    if minimum is not None and numeric < float(minimum):
        raise ValueError(f"{target} is below the declared minimum")
    if maximum is not None and numeric > float(maximum):
        raise ValueError(f"{target} exceeds the declared maximum")


def import_scheme_rows(
    pack: Mapping[str, object],
    rows: Iterable[Mapping[str, object]],
    source: str,
) -> SchemeImportResult:
    """Import rows while isolating malformed records.

    Historical data is allowed to be partial: unavailable declared values are
    left absent, which lets retrieval report missing features.  Values that
    are present (or have an explicit/default value) are strictly typed and
    checked against pack bounds.
    """

    source_label = str(source)
    specifications = _parameter_specs(pack)
    mappings = pack.get("mappings", {})
    if not isinstance(mappings, Mapping):
        raise ValueError("domain pack mappings must be an object")
    mapping_items = tuple(sorted(mappings.items(), key=lambda pair: str(pair[0])))
    records: list[SchemeRecord] = []
    rejected: list[dict[str, object]] = []
    for row_number, raw_row in enumerate(rows, start=1):
        if not isinstance(raw_row, Mapping):
            rejected.append(_rejection(row_number, source_label, "row_type", "row must be an object"))
            continue
        parameters: dict[str, object] = {}
        extensions: dict[str, object] = {}
        row_failed: tuple[str, str] | None = None
        # Map all known source fields in deterministic source-key order.
        for raw_key in sorted(raw_row, key=str):
            key = str(raw_key)
            value = raw_row[raw_key]
            mapping = mappings.get(key)
            if mapping is None:
                extensions[key] = value
                continue
            if not isinstance(mapping, Mapping):
                row_failed = ("mapping", f"mapping for {key!r} must be an object")
                break
            target = mapping.get("parameter")
            specification = specifications.get(str(target))
            if specification is None:
                row_failed = ("mapping", f"mapping for {key!r} targets an undeclared parameter")
                break
            if value is None or (isinstance(value, str) and not value.strip()):
                null_policy = mapping.get("null_policy", "ignore")
                if null_policy == "default" and "default" in mapping:
                    value = mapping["default"]
                elif null_policy == "reject":
                    row_failed = ("missing_value", f"{key!r} cannot be empty")
                    break
                else:
                    continue
            try:
                parsed = _parse_value(value, specification, mapping, str(target))
                _check_bounds(parsed, specification, str(target))
                target_name = str(target)
                if target_name in parameters and parameters[target_name] != parsed:
                    raise ValueError(f"multiple source fields map to {target_name}")
                parameters[target_name] = parsed
            except (TypeError, ValueError) as exc:
                row_failed = ("invalid_value", str(exc))
                break
        if row_failed is not None:
            rejected.append(_rejection(row_number, source_label, row_failed[0], row_failed[1]))
            continue

        # Apply defaults declared by either the source mapping or parameter
        # declaration, but retain partial rows when no default exists.
        for source_key, mapping in mapping_items:
            if not isinstance(mapping, Mapping):
                continue
            target = str(mapping.get("parameter", ""))
            if target in parameters or target not in specifications:
                continue
            if "default" in mapping:
                raw_default = mapping["default"]
            elif "default" in specifications[target]:
                raw_default = specifications[target]["default"]
            else:
                continue
            try:
                parameters[target] = _parse_value(raw_default, specifications[target], mapping, target)
                _check_bounds(parameters[target], specifications[target], target)
            except (TypeError, ValueError) as exc:
                row_failed = ("invalid_default", str(exc))
                break
        if row_failed is not None:
            rejected.append(_rejection(row_number, source_label, row_failed[0], row_failed[1]))
            continue

        parameter_tuple = tuple(sorted(parameters.items(), key=lambda pair: pair[0]))
        extension_tuple = tuple(sorted(extensions.items(), key=lambda pair: pair[0]))
        identity = (pack["id"], pack["version"], source_label, row_number, parameter_tuple)
        try:
            record_id = f"{pack['id_prefix']}-S-{canonical_hash(identity)[:12]}"
            content_hash = canonical_hash(
                {
                    "id": record_id,
                    "object_type": pack["object_type"],
                    "schema_version": pack.get("schema_version", 1),
                    "domain_pack_id": pack["id"],
                    "domain_pack_version": pack["version"],
                    "revision": 1,
                    "status": "imported",
                    "source": source_label,
                    "parameters": parameter_tuple,
                    "extensions": extension_tuple,
                }
            )
        except (TypeError, ValueError) as exc:
            rejected.append(_rejection(row_number, source_label, "unsupported_value", str(exc)))
            continue
        records.append(
            SchemeRecord(
                id=record_id,
                object_type=str(pack["object_type"]),
                schema_version=int(pack.get("schema_version", 1)),
                domain_pack_id=str(pack["id"]),
                domain_pack_version=int(pack["version"]),
                revision=1,
                status="imported",
                source=source_label,
                parameters=parameter_tuple,
                extensions=extension_tuple,
                content_hash=content_hash,
            )
        )
    return SchemeImportResult(tuple(records), tuple(rejected))


__all__ = ["SchemeImportResult", "import_scheme_rows"]
