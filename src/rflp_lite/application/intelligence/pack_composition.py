"""Deterministic selection and composition helpers for analysis domain packs."""

from __future__ import annotations

from collections.abc import Iterable

from rflp_lite.application.mbse_domain_packs import (
    list_domain_packs,
    load_composed_pack,
)
from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import ContractViolation


DEFAULT_BASE_PACK_ID = "common-v1"
_CATEGORIES = ("industry_pack_ids", "discipline_pack_ids", "overlay_pack_ids")
_BROAD_PACK_IDS = (
    "medical-v1",
    "aviation-v1",
    "automotive-v1",
    "industrial-v1",
    "energy-infrastructure-v1",
    "software-data-v1",
    "mechanical-v1",
    "electrical-v1",
    "software-v1",
    "control-v1",
    "thermal-v1",
    "safety-v1",
    "manufacturing-v1",
)


def _clone(value: object) -> object:
    import json

    return json.loads(canonical_json(value))


def _clean_id(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ContractViolation(f"{field} 必须是字符串")
    clean = value.strip()
    if (
        not clean
        or clean in {".", ".."}
        or clean != clean.rsplit("/", 1)[-1]
        or "/" in clean
        or "\\" in clean
        or "\x00" in clean
    ):
        raise ContractViolation(f"{field} 包含非法领域包 ID")
    return clean.removesuffix(".json")


def _ids(value: object, *, field: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise ContractViolation(f"{field} 必须是字符串数组")
    result: list[str] = []
    for raw in value:
        pack_id = _clean_id(raw, field=field)
        if pack_id not in result:
            result.append(pack_id)
    return result


def _legacy_selection(value: dict[str, object]) -> tuple[str, list[str]]:
    """Translate the previous single ``domain_pack_id`` setting."""

    raw_id = value.get("domain_pack_id")
    if raw_id in (None, ""):
        return DEFAULT_BASE_PACK_ID, []
    pack_id = _clean_id(raw_id, field="domain_pack_id")
    if pack_id == DEFAULT_BASE_PACK_ID:
        return pack_id, []
    return DEFAULT_BASE_PACK_ID, [pack_id]


def normalize_pack_selection(value: object) -> dict[str, object]:
    """Normalize the four-layer selection and retain old API fields."""

    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ContractViolation("领域包选择必须是对象")

    legacy_base, legacy_overlays = _legacy_selection(value)
    base = _clean_id(
        value.get("base_pack_id", legacy_base), field="base_pack_id"
    )
    categories: dict[str, list[str]] = {
        field: _ids(value.get(field), field=field) for field in _CATEGORIES
    }
    if not any(field in value for field in _CATEGORIES):
        categories["overlay_pack_ids"] = legacy_overlays

    all_ids = [base, *categories["industry_pack_ids"], *categories["discipline_pack_ids"], *categories["overlay_pack_ids"]]
    duplicates = sorted({pack_id for pack_id in all_ids if all_ids.count(pack_id) > 1})
    if duplicates:
        raise ContractViolation(f"领域包选择存在重复 ID: {', '.join(duplicates)}")

    available = set(list_domain_packs())
    unknown = [pack_id for pack_id in all_ids if pack_id not in available]
    if unknown:
        raise ContractViolation(f"领域包不存在: {', '.join(unknown)}")

    provenance = value.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {"source": "default", "reason": "common-mbse-pack"}
    normalized: dict[str, object] = {
        "base_pack_id": base,
        **categories,
        "provenance": _clone(provenance),
    }
    explicit_enabled = bool(value.get("enabled", False))
    selected_non_common = any(categories.values()) or base != DEFAULT_BASE_PACK_ID
    legacy_id = value.get("domain_pack_id")
    normalized.update(
        {
            "enabled": explicit_enabled or selected_non_common,
            "domain_pack_id": (
                _clean_id(legacy_id, field="domain_pack_id")
                if legacy_id not in (None, "")
                else None
            ),
            "domain_pack_version": value.get("domain_pack_version"),
        }
    )
    return normalized


def compose_pack_selection(selection: dict[str, object]) -> dict[str, object]:
    """Load the normalized selection and return its merged, traceable guidance."""

    normalized = normalize_pack_selection(selection)
    pack_ids = [
        str(normalized["base_pack_id"]),
        *[str(item) for item in normalized["industry_pack_ids"]],
        *[str(item) for item in normalized["discipline_pack_ids"]],
        *[str(item) for item in normalized["overlay_pack_ids"]],
    ]
    composed = load_composed_pack({"pack_ids": pack_ids})
    composed["selection"] = _clone(normalized)
    composed["pack_ids"] = pack_ids
    composed["pack_selection_hash"] = pack_selection_hash(normalized)
    return composed


def pack_selection_hash(selection: dict[str, object]) -> str:
    """Return a stable hash for selection identity, independent of dict order."""

    normalized = normalize_pack_selection(selection)
    identity = {
        "base_pack_id": normalized["base_pack_id"],
        "industry_pack_ids": normalized["industry_pack_ids"],
        "discipline_pack_ids": normalized["discipline_pack_ids"],
        "overlay_pack_ids": normalized["overlay_pack_ids"],
    }
    return canonical_hash(identity)


def available_analysis_pack_ids() -> tuple[str, ...]:
    """Return only the broad reusable packs intended for project analysis."""

    available = set(list_domain_packs())
    return tuple(
        pack_id
        for pack_id in (DEFAULT_BASE_PACK_ID, *_BROAD_PACK_IDS, "urban-medical-aam-v1")
        if pack_id in available
    )


__all__ = [
    "DEFAULT_BASE_PACK_ID",
    "available_analysis_pack_ids",
    "compose_pack_selection",
    "normalize_pack_selection",
    "pack_selection_hash",
]
