"""Strict, review-gated implicit requirement suggestions."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from rflp_lite.domain.errors import AdapterFailure
from rflp_lite.domain.requirements import DocumentRegion, StructuredRequirement
from rflp_lite.ports.generative_model import GenerationRequest, GenerativeModel


_REQUIRED = {
    "source_region_id",
    "statement",
    "entities",
    "constraints",
    "verification_method",
    "confidence",
}

_RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "maxItems": 32,
            "items": {
                "type": "object",
                "required": sorted(_REQUIRED),
                "properties": {
                    "source_region_id": {"type": "string", "minLength": 1, "maxLength": 120},
                    "statement": {"type": "string", "minLength": 1, "maxLength": 2000},
                    "entities": {"type": "array", "items": {"type": "string", "maxLength": 240}, "maxItems": 32},
                    "constraints": {"type": "array", "maxItems": 32, "items": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "string", "maxLength": 240}}},
                    "verification_method": {"type": "string", "minLength": 1, "maxLength": 120},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "additionalProperties": False,
            },
        }
    },
    "additionalProperties": False,
}


def suggest_implicit_requirements(
    regions: tuple[DocumentRegion, ...],
    config: dict[str, object],
    complete: Callable[[dict[str, object], object], str] | None = None,
    model: GenerativeModel | None = None,
) -> tuple[StructuredRequirement, ...]:
    """Ask an approved model for *suggestions*, validating every source link."""

    source_ids = {region.id for region in regions}
    prompt = {
        "task": "只提出文本中隐含但未明确写出的工程约束；不得改写原文，不得批准结果。",
        "schema": sorted(_REQUIRED),
        "regions": [{"id": region.id, "text": region.text} for region in regions],
    }
    if complete is None:
        if model is None:
            raise AdapterFailure("LLM 未配置")
        response = model.complete_json(
            GenerationRequest(
                lens_id="requirements.implicit_constraints",
                system_prompt="你是需求工程审查助手，只能输出符合 response_schema 的 JSON 对象。",
                user_payload=prompt,
                response_schema=_RESPONSE_SCHEMA,
                max_tokens=1800,
            )
        )
        payload = response.payload
        value = payload.get("items") if isinstance(payload, dict) else None
    else:
        content = complete(config, prompt)
        try:
            value = json.loads(content)
        except (TypeError, json.JSONDecodeError) as exc:
            raise AdapterFailure("LLM implicit requirement output is not valid JSON") from exc
    if not isinstance(value, list):
        raise AdapterFailure("LLM implicit requirement output must be an array")
    result: list[StructuredRequirement] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != _REQUIRED:
            raise AdapterFailure("LLM implicit requirement schema is invalid")
        source_id = str(item["source_region_id"])
        if source_id not in source_ids:
            raise AdapterFailure("LLM implicit requirement source_region_id is invalid")
        try:
            confidence = float(item["confidence"])
        except (TypeError, ValueError) as exc:
            raise AdapterFailure("LLM implicit requirement confidence is invalid") from exc
        if not 0.0 <= confidence <= 1.0:
            raise AdapterFailure("LLM implicit requirement confidence is invalid")
        if not isinstance(item["entities"], list) or not isinstance(item["constraints"], list):
            raise AdapterFailure("LLM implicit requirement arrays are invalid")
        constraints: list[tuple[str, str]] = []
        for pair in item["constraints"]:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                raise AdapterFailure("LLM implicit requirement constraints are invalid")
            constraints.append((str(pair[0]), str(pair[1])))
        region = next(region for region in regions if region.id == source_id)
        result.append(
            StructuredRequirement.from_fields(
                region=region,
                subject="系统",
                predicate="隐含约束",
                statement=str(item["statement"]).strip(),
                source_type="inferred",
                entities=tuple(str(entity) for entity in item["entities"]),
                constraints=tuple(constraints),
                verification_method=str(item["verification_method"]).strip() or "review",
                confidence=confidence,
                producer="llm",
            )
        )
    return tuple(result)


def inferred_requirement_payloads(
    regions: tuple[DocumentRegion, ...],
    config: dict[str, object],
    complete: Callable[[dict[str, object], object], str] | None = None,
    model: GenerativeModel | None = None,
) -> tuple[dict[str, object], ...]:
    """JSON-safe helper used by Web/API layers."""

    from rflp_lite.application.requirement_semantics import requirement_payload

    return tuple(
        requirement_payload(item, producer="llm")
        | {"bulk_approvable": False}
        for item in suggest_implicit_requirements(regions, config, complete, model)
    )
