"""Strict, versioned JSON Schemas for the project-analysis blocks."""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy

from rflp_lite.domain.errors import ContractViolation


BLOCK_SCHEMA_VERSION = "v2"

_DIAGNOSTIC = {
    "type": "object",
    "required": ["code", "severity", "message"],
    "properties": {
        "code": {"type": "string", "minLength": 1, "maxLength": 120},
        "severity": {"type": "string", "enum": ["info", "warning", "error"]},
        "message": {"type": "string", "minLength": 1, "maxLength": 1000},
        "path": {"type": "string", "maxLength": 300},
    },
    "additionalProperties": False,
}

_CONFIDENCE = {"type": "number", "minimum": 0, "maximum": 1}
_SOURCE_IDS = {
    "type": "array",
    "items": {"type": "string", "minLength": 1, "maxLength": 120},
    "maxItems": 256,
    "uniqueItems": True,
}
_TEXT = {"type": "string", "minLength": 1, "maxLength": 2000}
_SHORT_TEXT = {"type": "string", "minLength": 1, "maxLength": 240}
_TEXT_LIST = {
    "type": "array",
    "items": _SHORT_TEXT,
    "maxItems": 32,
}


def _envelope(item_schema: dict[str, object], max_items: int) -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "AI4MBSE analysis block",
        "type": "object",
        "required": ["items", "diagnostics"],
        "properties": {
            "schema_version": {"const": BLOCK_SCHEMA_VERSION},
            "block_id": {"type": "string", "minLength": 1, "maxLength": 80},
            "input_hash": {"type": "string", "minLength": 1, "maxLength": 128},
            "workspace": {"type": "string", "maxLength": 500},
            "items": {
                "type": "array",
                "maxItems": max_items,
                "items": item_schema,
            },
            "diagnostics": {
                "type": "array",
                "maxItems": 64,
                "items": _DIAGNOSTIC,
            },
            "coverage_decisions": {
                "type": "array",
                "maxItems": 128,
                "items": {
                    "type": "object",
                    "required": [
                        "decision_type",
                        "key",
                        "status",
                        "rationale",
                        "source_requirement_ids",
                    ],
                    "properties": {
                        "id": {"type": "string", "minLength": 1, "maxLength": 120},
                        "decision_type": {
                            "type": "string",
                            "enum": [
                                "scenario_type",
                                "scenario_dimension",
                                "lifecycle_phase",
                                "stakeholder_category",
                                "architecture_dimension",
                            ],
                        },
                        "key": {"type": "string", "minLength": 1, "maxLength": 120},
                        "status": {"const": "not_applicable"},
                        "rationale": {"type": "string", "minLength": 1, "maxLength": 2000},
                        "source_requirement_ids": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1, "maxLength": 120},
                            "minItems": 1,
                            "maxItems": 256,
                            "uniqueItems": True,
                        },
                    },
                    "additionalProperties": False,
                },
            },
        },
        "additionalProperties": False,
    }


_SYSTEM_SCOPE = {
    "type": "object",
    "required": ["id", "name", "domain", "mission", "source_region_ids", "confidence"],
    "properties": {
        "id": {"type": "string", "minLength": 1, "maxLength": 120},
        "name": _SHORT_TEXT,
        "domain": _SHORT_TEXT,
        "mission": _TEXT,
        "source_region_ids": _SOURCE_IDS,
        "confidence": _CONFIDENCE,
    },
    "additionalProperties": False,
}

_STAKEHOLDER = {
    "type": "object",
    "required": ["id", "name", "category", "goals", "interactions", "source_region_ids", "confidence"],
    "properties": {
        "id": {"type": "string", "minLength": 1, "maxLength": 120},
        "name": _SHORT_TEXT,
        "category": {"type": "string", "enum": ["user", "end_user", "operator", "owner", "customer", "engineering", "regulator", "supplier", "external_system", "environment", "system", "other"]},
        "goals": _TEXT_LIST,
        "interactions": _TEXT_LIST,
        "source_region_ids": _SOURCE_IDS,
        "confidence": _CONFIDENCE,
    },
    "additionalProperties": False,
}

_CONCERN = {
    "type": "object",
    "required": ["kind", "id", "name", "stakeholder_id", "source_region_ids", "confidence"],
    "properties": {
        "kind": {"const": "concern"},
        "id": {"type": "string", "minLength": 1, "maxLength": 120},
        "name": _SHORT_TEXT,
        "statement": _TEXT,
        "stakeholder_id": {"type": "string", "minLength": 1, "maxLength": 120},
        "source_region_ids": _SOURCE_IDS,
        "confidence": _CONFIDENCE,
    },
    "additionalProperties": False,
}

_NEED = {
    "type": "object",
    "required": ["kind", "id", "statement", "stakeholder_id", "concern_id", "source_region_ids", "confidence"],
    "properties": {
        "kind": {"const": "need"},
        "id": {"type": "string", "minLength": 1, "maxLength": 120},
        "statement": _TEXT,
        "name": _SHORT_TEXT,
        "stakeholder_id": {"type": "string", "minLength": 1, "maxLength": 120},
        "concern_id": {"type": "string", "minLength": 1, "maxLength": 120},
        "source_region_ids": _SOURCE_IDS,
        "confidence": _CONFIDENCE,
    },
    "additionalProperties": False,
}

_REQUIREMENT = {
    "type": "object",
    "required": ["id", "statement", "subject", "predicate", "verification_method", "source_region_ids", "confidence"],
    "properties": {
        "id": {"type": "string", "minLength": 1, "maxLength": 120},
        "statement": _TEXT,
        "subject": _SHORT_TEXT,
        "predicate": {"type": "string", "enum": ["shall", "should", "must", "应", "应该", "必须"]},
        "verification_method": {"type": "string", "enum": ["analysis", "inspection", "test", "simulation", "demonstration", "分析", "检查", "测试", "仿真", "演示"]},
        "source_type": {"type": "string", "enum": ["explicit", "inferred", "manual", "constraint", "implicit"]},
        "source_region_ids": _SOURCE_IDS,
        "confidence": _CONFIDENCE,
    },
    "additionalProperties": False,
}

_ATTRIBUTE = {
    "type": "object",
    "required": ["kind", "id", "requirement_id", "name", "value", "unit", "source_region_ids", "confidence"],
    "properties": {
        "kind": {"const": "attribute"},
        "id": {"type": "string", "minLength": 1, "maxLength": 120},
        "requirement_id": {"type": "string", "minLength": 1, "maxLength": 120},
        "name": _SHORT_TEXT,
        "value": {"type": "string", "maxLength": 240},
        "unit": {"type": "string", "maxLength": 40},
        "minimum": {"type": "string", "maxLength": 80},
        "maximum": {"type": "string", "maxLength": 80},
        "enum_values": _TEXT_LIST,
        "source_region_ids": _SOURCE_IDS,
        "confidence": _CONFIDENCE,
    },
    "additionalProperties": False,
}

_CONSTRAINT = {
    "type": "object",
    "required": ["kind", "id", "requirement_ids", "constraint_type", "expression", "explicitness", "source_region_ids", "confidence"],
    "properties": {
        "kind": {"const": "constraint"},
        "id": {"type": "string", "minLength": 1, "maxLength": 120},
        "requirement_ids": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 120}, "minItems": 1, "maxItems": 64, "uniqueItems": True},
        "constraint_type": _SHORT_TEXT,
        "expression": _TEXT,
        "explicitness": {"const": "explicit"},
        "rationale": {"type": "string", "maxLength": 2000},
        "verification_method": {"type": "string", "maxLength": 120},
        "source_region_ids": _SOURCE_IDS,
        "confidence": _CONFIDENCE,
    },
    "additionalProperties": False,
}

_IMPLICIT_CONSTRAINT = {
    "type": "object",
    "required": ["kind", "id", "requirement_ids", "constraint_type", "expression", "explicitness", "rationale", "verification_method", "source_region_ids", "confidence"],
    "properties": {
        "kind": {"const": "constraint"},
        "id": {"type": "string", "minLength": 1, "maxLength": 120},
        "requirement_ids": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 120}, "minItems": 1, "maxItems": 64, "uniqueItems": True},
        "constraint_type": _SHORT_TEXT,
        "expression": _TEXT,
        "explicitness": {"const": "inferred"},
        "rationale": _TEXT,
        "verification_method": {"type": "string", "minLength": 1, "maxLength": 120},
        "source_region_ids": _SOURCE_IDS,
        "confidence": _CONFIDENCE,
    },
    "additionalProperties": False,
}

_SCENARIO = {
    "type": "object",
    "required": ["id", "title", "scenario_type", "actors", "steps", "expected_outcomes", "requirement_ids", "source_region_ids", "confidence"],
    "properties": {
        "id": {"type": "string", "minLength": 1, "maxLength": 120},
        "title": _SHORT_TEXT,
        "scenario_type": {"type": "string", "enum": ["normal", "boundary", "failure", "recovery", "misuse"]},
        "coverage_dimensions": {"type": "array", "items": _SHORT_TEXT, "maxItems": 32, "uniqueItems": True},
        "lifecycle_phase": {"type": "string", "maxLength": 120},
        "description": _TEXT,
        "trigger": _TEXT,
        "actors": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 120}, "maxItems": 24, "uniqueItems": True},
        "stakeholder_ids": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 120}, "maxItems": 64, "uniqueItems": True},
        "recovery_steps": _TEXT_LIST,
        "steps": {"type": "array", "items": _TEXT, "minItems": 1, "maxItems": 32},
        "expected_outcomes": {"type": "array", "items": _TEXT, "minItems": 1, "maxItems": 32},
        "requirement_ids": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 120}, "maxItems": 32, "uniqueItems": True},
        "source_region_ids": _SOURCE_IDS,
        "confidence": _CONFIDENCE,
    },
    "additionalProperties": False,
}

_RELATION = {
    "type": "object",
    "required": ["kind", "id", "source_id", "predicate", "target_id", "source_region_ids", "confidence"],
    "properties": {
        "kind": {"const": "relation"},
        "id": {"type": "string", "minLength": 1, "maxLength": 120},
        "source_id": {"type": "string", "minLength": 1, "maxLength": 120},
        "predicate": {"type": "string", "minLength": 1, "maxLength": 80},
        "target_id": {"type": "string", "minLength": 1, "maxLength": 120},
        "source_region_ids": _SOURCE_IDS,
        "confidence": _CONFIDENCE,
    },
    "additionalProperties": False,
}

_ARCHITECTURE_ENTITY = {
    "type": "object",
    "required": ["kind", "id", "name", "description", "requirement_ids", "source_region_ids", "confidence"],
    "properties": {
        "kind": {"type": "string", "enum": ["function", "logical_component", "physical_component", "interface"]},
        "id": {"type": "string", "minLength": 1, "maxLength": 120},
        "name": _SHORT_TEXT,
        "description": _TEXT,
        "lifecycle_phase": {"type": "string", "maxLength": 120},
        "requirement_ids": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 120}, "maxItems": 32, "uniqueItems": True},
        "source_id": {"type": "string", "minLength": 1, "maxLength": 120},
        "target_id": {"type": "string", "minLength": 1, "maxLength": 120},
        "source_region_ids": _SOURCE_IDS,
        "confidence": _CONFIDENCE,
    },
    "additionalProperties": False,
}

_SCHEMAS: dict[str, dict[str, object]] = {
    "system_scope": _envelope(_SYSTEM_SCOPE, 1),
    "stakeholders": _envelope(_STAKEHOLDER, 12),
    "concerns_needs": _envelope({"oneOf": [_CONCERN, _NEED]}, 18),
    "requirements": _envelope(_REQUIREMENT, 16),
    "requirement_details": _envelope({"oneOf": [_ATTRIBUTE, _CONSTRAINT]}, 32),
    "implicit_constraints": _envelope(_IMPLICIT_CONSTRAINT, 32),
    "scenarios": _envelope(_SCENARIO, 10),
    "architecture": _envelope({"oneOf": [_ARCHITECTURE_ENTITY, _RELATION]}, 18),
}

# All block entities use the same operation vocabulary.  Operations are
# optional for backwards-compatible model fixtures; the reconciler applies
# ``upsert_entity`` when omitted and rejects destructive operations.
_OPERATION = {
    "type": "string",
    "enum": [
        "upsert_entity",
        "enrich_fields",
        "propose_change",
        "flag_for_review",
        "add_relation",
    ],
}
for _schema in _SCHEMAS.values():
    _item = _schema["properties"]["items"]["items"]
    _schemas_to_update = _item.get("oneOf", [_item]) if isinstance(_item, dict) else []
    for _candidate in _schemas_to_update:
        if isinstance(_candidate, dict):
            props = _candidate.setdefault("properties", {})
            props.update(
                {
                    "operation": _OPERATION,
                    "target_id": {"type": "string", "minLength": 1, "maxLength": 120},
                    "review_hint": {"type": "string", "maxLength": 2000},
                    "source_item_id": {"type": "string", "maxLength": 120},
                }
            )
            if _candidate.get("additionalProperties") is False:
                # The fields above are intentionally the only control metadata
                # that model output may carry across the strict boundary.
                _candidate["additionalProperties"] = False


def _inject_source_region_enum(
    schema: dict[str, object], source_region_ids: tuple[str, ...]
) -> None:
    for key, value in schema.items():
        if key == "source_region_ids" and isinstance(value, dict):
            items = value.get("items")
            if isinstance(items, dict):
                items["enum"] = list(source_region_ids)
        elif isinstance(value, dict):
            _inject_source_region_enum(value, source_region_ids)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _inject_source_region_enum(item, source_region_ids)


def schema_for(
    block_id: str, source_region_ids: Iterable[str] = ()
) -> dict[str, object]:
    try:
        schema = deepcopy(_SCHEMAS[block_id])
    except KeyError as exc:
        raise ContractViolation(f"未知分析块: {block_id}") from exc
    allowed = tuple(
        sorted({str(value).strip() for value in source_region_ids if str(value).strip()})
    )
    if allowed:
        _inject_source_region_enum(schema, allowed)
    return schema


def block_schema_version(block_id: str) -> str:
    schema_for(block_id)
    return BLOCK_SCHEMA_VERSION


__all__ = ["BLOCK_SCHEMA_VERSION", "block_schema_version", "schema_for"]
