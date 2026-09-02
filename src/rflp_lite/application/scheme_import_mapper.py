"""Normalize versioned historical scheme data for the concept workflow."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from rflp_lite.application.scheme_library import (
    SchemeImportResult,
    _check_bounds,
    _parameter_specs,
    _parse_value,
    _rejection,
)
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.concept_design import SchemeRecord


_ID_KEYS = ("scheme_id", "方案ID", "方案编号", "id")
_UNIFIED_FIELDS: dict[str, tuple[str, str | None]] = {
    "span_m": ("span_m", "m"),
    "翼展": ("span_m", None),
    "wing_area_m2": ("wing_area_m2", "m2"),
    "机翼面积": ("wing_area_m2", None),
    "fuselage_length_m": ("fuselage_length_m", "m"),
    "机身长度": ("fuselage_length_m", None),
    "empty_mass_kg": ("mass_kg", "kg"),
    "空机质量": ("mass_kg", None),
    "mass_kg": ("mass_kg", "kg"),
    "payload_kg": ("payload_kg", "kg"),
    "任务载荷": ("payload_kg", None),
    "cruise_speed_kmh": ("cruise_speed_mps", "km/h"),
    "cruise_speed_mps": ("cruise_speed_mps", "m/s"),
    "巡航速度": ("cruise_speed_mps", None),
    "section_modulus_m3": ("section_modulus_m3", "m3"),
    "allowable_stress_pa": ("allowable_stress_pa", "Pa"),
    "cg_x_m": ("cg_x_m", "m"),
}
_EXTENSION_FIELDS = {"name", "方案名称", "task_type", "任务类型", "mtow_kg", "最大起飞重量", "range_km", "航程"}
_ID_PATTERN = re.compile(r"^[^\s]{1,128}$")


def _field_mapping(pack: Mapping[str, object], key: str) -> Mapping[str, object] | None:
    unified = _UNIFIED_FIELDS.get(key)
    if unified is not None:
        parameter, unit = unified
        result: dict[str, object] = {"parameter": parameter}
        if unit:
            result["source_unit"] = unit
        return result
    mappings = pack.get("mappings", {})
    value = mappings.get(key) if isinstance(mappings, Mapping) else None
    return value if isinstance(value, Mapping) else None


def _stable_id(pack: Mapping[str, object], source: str, row_number: int, parameters: Mapping[str, object], explicit: object) -> str:
    if explicit not in (None, ""):
        identifier = str(explicit).strip()
        if not _ID_PATTERN.fullmatch(identifier):
            raise ValueError("scheme_id must be a non-empty value without whitespace and no longer than 128 characters")
        return identifier
    identity = (pack.get("id"), pack.get("version"), str(source), row_number, tuple(sorted(parameters.items())))
    return f"{pack['id_prefix']}-S-{canonical_hash(identity)[:12]}"


def map_scheme_rows(
    pack: Mapping[str, object],
    rows: Iterable[Mapping[str, object]],
    source: str,
    *,
    existing_ids: set[str] | frozenset[str] = frozenset(),
    apply_defaults: bool = False,
) -> SchemeImportResult:
    """Map fixed-wing history while preserving absent source features.

    ``existing_ids`` is used by the Demo seed path to make initialization
    idempotent.  Missing source columns remain missing; ``apply_defaults`` is
    retained for the legacy generic importer.
    """

    specifications = _parameter_specs(pack)
    mappings = pack.get("mappings", {})
    if not isinstance(mappings, Mapping):
        raise ValueError("domain pack mappings must be an object")
    accepted: list[SchemeRecord] = []
    rejected: list[dict[str, object]] = []
    skipped: list[str] = []
    seen_ids = set(existing_ids)
    for row_number, raw_row in enumerate(rows, start=1):
        if not isinstance(raw_row, Mapping):
            rejected.append(_rejection(row_number, str(source), "row_type", "row must be an object"))
            continue
        parameters: dict[str, object] = {}
        extensions: dict[str, object] = {}
        explicit_id = next((raw_row[key] for key in _ID_KEYS if key in raw_row), None)
        failed: tuple[str, str] | None = None
        for raw_key in sorted(raw_row, key=str):
            key = str(raw_key)
            value = raw_row[raw_key]
            if key in _ID_KEYS:
                continue
            if key in _EXTENSION_FIELDS:
                extensions[key] = value
                continue
            mapping = _field_mapping(pack, key)
            if mapping is None:
                extensions[key] = value
                continue
            target = str(mapping.get("parameter", ""))
            specification = specifications.get(target)
            if specification is None:
                failed = ("mapping", f"mapping for {key!r} targets an undeclared parameter")
                break
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            try:
                parsed = _parse_value(value, specification, mapping, target)
                _check_bounds(parsed, specification, target)
                if target in parameters and parameters[target] != parsed:
                    raise ValueError(f"multiple source fields map to {target}")
                parameters[target] = parsed
            except (TypeError, ValueError) as exc:
                failed = ("invalid_value", str(exc))
                break
        if failed is not None:
            rejected.append(_rejection(row_number, str(source), failed[0], failed[1]))
            continue

        if apply_defaults:
            for target, specification in specifications.items():
                if target not in parameters and "default" in specification:
                    try:
                        parameters[target] = _parse_value(specification["default"], specification, {}, target)
                    except (TypeError, ValueError) as exc:
                        failed = ("invalid_default", str(exc))
                        break
        if failed is not None:
            rejected.append(_rejection(row_number, str(source), failed[0], failed[1]))
            continue

        try:
            record_id = _stable_id(pack, str(source), row_number, parameters, explicit_id)
        except ValueError as exc:
            rejected.append(_rejection(row_number, str(source), "invalid_id", str(exc)))
            continue
        if record_id in seen_ids:
            skipped.append(record_id)
            continue
        seen_ids.add(record_id)
        parameter_tuple = tuple(sorted(parameters.items(), key=lambda pair: pair[0]))
        extension_tuple = tuple(sorted(extensions.items(), key=lambda pair: pair[0]))
        payload = {
            "id": record_id,
            "object_type": pack["object_type"],
            "schema_version": pack.get("schema_version", 1),
            "domain_pack_id": pack["id"],
            "domain_pack_version": pack["version"],
            "revision": 1,
            "status": "imported",
            "source": str(source),
            "parameters": parameter_tuple,
            "extensions": extension_tuple,
        }
        content_hash = canonical_hash(payload)
        accepted.append(
            SchemeRecord(
                id=record_id,
                object_type=str(pack["object_type"]),
                schema_version=int(pack.get("schema_version", 1)),
                domain_pack_id=str(pack["id"]),
                domain_pack_version=int(pack["version"]),
                revision=1,
                status="imported",
                source=str(source),
                parameters=parameter_tuple,
                extensions=extension_tuple,
                content_hash=content_hash,
            )
        )
    return SchemeImportResult(tuple(accepted), tuple(rejected), tuple(skipped))


import_scheme_rows = map_scheme_rows


__all__ = ["SchemeImportResult", "import_scheme_rows", "map_scheme_rows"]
