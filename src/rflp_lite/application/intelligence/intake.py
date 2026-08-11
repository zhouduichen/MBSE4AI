"""Deterministic intake and seed extraction from sparse user input."""

from __future__ import annotations

import json

from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import ContractViolation


def _regions(state: dict[str, object]) -> list[dict[str, object]]:
    values = state.get("document_regions") or state.get("spans") or []
    return [
        item
        for item in values
        if isinstance(item, dict) and str(item.get("text", "")).strip()
    ]


def build_seed_model(state: dict[str, object], pack: dict[str, object]) -> dict[str, object]:
    regions = _regions(state)
    if not regions:
        raise ContractViolation("discovery requires at least one non-empty input region")
    text = "\n".join(str(item["text"]).strip() for item in regions)
    application_type = "城市医疗" if "城市" in text and "医疗" in text else "未分类应用"
    if "飞行汽车" in text:
        system_name = "城市医疗用途的飞行汽车" if application_type == "城市医疗" else "飞行汽车"
    else:
        system_name = str(pack.get("display_name", "待定义系统"))
    seed = {
        "system_name": system_name,
        "application_type": application_type,
        "mission_statement": text,
        "source_region_ids": [str(item.get("id", "")) for item in regions],
        "explicit_constraints": [],
        "unknowns": [
            "operating_boundary",
            "target_users",
            "regulatory_jurisdiction",
            "performance_envelope",
            "acceptance_criteria",
        ],
        "pack_id": str(pack["id"]),
    }
    return {**seed, "seed_hash": canonical_hash(seed)}


def attach_seed_model(state: dict[str, object], pack: dict[str, object]) -> dict[str, object]:
    result = json.loads(canonical_json(state))
    discovery = result.setdefault("discovery", {})
    if not isinstance(discovery, dict):
        raise ContractViolation("discovery state must be an object")
    discovery["intake"] = build_seed_model(result, pack)
    discovery["revision"] = int(discovery.get("revision", 0)) + 1
    return result
