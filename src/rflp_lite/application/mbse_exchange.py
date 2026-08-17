"""Versioned JSON and conservative SysML-v2-subset exchange for MBSE views."""

from __future__ import annotations

import json
import re

from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.application.mbse_semantics import validate_mbse_semantic_model


FORMAT = "ai4mbse/mbse"
VERSION = 1
PACKAGE = "AI4MBSE_MBSE"
_META = re.compile(r"^\s*//\s*mbse-model\s+(\{.*\})\s*$")
_STATE_META = re.compile(r"^\s*//\s*mbse-model-state\s+(\{.*\})\s*$")
_SEMANTIC_META = re.compile(r"^\s*//\s*mbse-semantic-model\s+(\{.*\})\s*$")


def validate_mbse_model(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ContractViolation("MBSE model must be an object")
    required = ("actors", "use_cases", "activities", "lifelines", "messages", "trace_links")
    result: dict[str, object] = {key: [] for key in required}
    for key in required:
        collection = value.get(key)
        if not isinstance(collection, list):
            raise ContractViolation(f"MBSE model requires {key} array")
        ids: set[str] = set()
        normalized: list[dict[str, object]] = []
        for item in collection:
            if not isinstance(item, dict):
                raise ContractViolation(f"MBSE {key} items require IDs")
            item_id = str(item.get("id", ""))
            if not item_id and key == "trace_links":
                item_id = f"trace-{canonical_hash((item.get('source_id'), item.get('predicate'), item.get('target_id')))[:12]}"
            if not item_id:
                raise ContractViolation(f"MBSE {key} items require IDs")
            item = {**item, "id": item_id}
            if item_id in ids:
                raise ContractViolation(f"MBSE {key} IDs must be unique")
            ids.add(item_id)
            normalized.append(json.loads(canonical_json(item)))
        result[key] = normalized
    result["format"] = str(value.get("format", FORMAT))
    result["version"] = int(value.get("version", VERSION))
    result["status"] = str(value.get("status", "review"))
    result["revision"] = str(value.get("revision", canonical_hash(result)))
    result["review_history"] = json.loads(canonical_json(value.get("review_history", ())))
    semantic_model = value.get("semantic_model")
    if semantic_model is not None:
        issues = validate_mbse_semantic_model(semantic_model)
        if issues:
            raise ContractViolation(
                f"MBSE semantic model invalid: {'; '.join(issues[:6])}"
            )
        result["semantic_model"] = json.loads(canonical_json(semantic_model))
        result["semantic_model_version"] = int(
            result["semantic_model"].get("version", 0)
        )
    if result["format"] != FORMAT or result["version"] != VERSION:
        raise ContractViolation("unsupported MBSE exchange format or version")
    return result


def export_mbse_json(model: object) -> dict[str, object]:
    normalized = validate_mbse_model(model)
    return {
        "format": FORMAT,
        "version": VERSION,
        "model": normalized,
        "model_hash": canonical_hash(normalized),
    }


def import_mbse_json(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict) or payload.get("format") != FORMAT or payload.get("version") != VERSION:
        raise ContractViolation("unsupported MBSE exchange format or version")
    model = validate_mbse_model(payload.get("model"))
    declared_hash = payload.get("model_hash")
    if declared_hash is not None and declared_hash != canonical_hash(model):
        raise ContractViolation("MBSE model_hash does not match model")
    return model


def export_mbse_sysml_v2_text(model: object) -> str:
    normalized = validate_mbse_model(model)
    lines = [f"package {PACKAGE} {{", f"  // mbse-model-hash {canonical_hash(normalized)}"]
    lines.append(
        f"  // mbse-model-state {canonical_json({'status': normalized['status'], 'revision': normalized['revision'], 'review_history': normalized['review_history']})}"
    )
    if normalized.get("semantic_model"):
        lines.append(f"  // mbse-semantic-model {canonical_json(normalized['semantic_model'])}")
    for key in ("actors", "use_cases", "activities", "lifelines", "messages", "trace_links"):
        for item in normalized[key]:
            lines.append(f"  // mbse-model {canonical_json({'collection': key, 'item': item})}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def import_mbse_sysml_v2_text(text: str) -> dict[str, object]:
    if not isinstance(text, str) or not text.strip().startswith(f"package {PACKAGE} {{"):
        raise ContractViolation(f"expected package {PACKAGE}")
    collections = {key: [] for key in ("actors", "use_cases", "activities", "lifelines", "messages", "trace_links")}
    declared_hash = None
    state_meta: dict[str, object] = {}
    semantic_model: dict[str, object] | None = None
    for line in text.splitlines():
        if "mbse-model-hash" in line:
            declared_hash = line.split("mbse-model-hash", 1)[1].strip()
        state_match = _STATE_META.match(line)
        if state_match:
            try:
                state_meta = json.loads(state_match.group(1))
            except json.JSONDecodeError as exc:
                raise ContractViolation("invalid MBSE model state metadata") from exc
            continue
        semantic_match = _SEMANTIC_META.match(line)
        if semantic_match:
            try:
                semantic_model = json.loads(semantic_match.group(1))
            except json.JSONDecodeError as exc:
                raise ContractViolation("invalid MBSE semantic model metadata") from exc
            continue
        match = _META.match(line)
        if not match:
            continue
        try:
            value = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise ContractViolation("invalid MBSE model metadata") from exc
        collection = value.get("collection")
        if collection not in collections or not isinstance(value.get("item"), dict):
            raise ContractViolation("invalid MBSE model collection")
        collections[collection].append(value["item"])
    model = validate_mbse_model(
        {
            "format": FORMAT,
            "version": VERSION,
            **collections,
            **state_meta,
            **({"semantic_model": semantic_model} if semantic_model is not None else {}),
        }
    )
    if declared_hash and declared_hash != canonical_hash(model):
        raise ContractViolation("MBSE model hash does not match metadata")
    return model
