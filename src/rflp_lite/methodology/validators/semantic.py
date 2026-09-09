"""Small deterministic semantic lint for high-value entity payloads."""

from __future__ import annotations

import re
from collections.abc import Mapping

from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.errors import MethodologyValidationError
from rflp_lite.domain.model import AddEntity, UpdateEntity
from rflp_lite.methodology.validation import ValidationContext


_HARDWARE_WORDS = re.compile(
    r"(?:sensor|芯片|传感器|数据库|database|arduino|raspberry|stm32|型号|part[- ]?number)", re.I
)


def _payloads(context: ValidationContext):
    index = context.graph.entity_index
    for operation in context.response.patch.operations if context.response.patch else ():
        if isinstance(operation, AddEntity):
            yield operation.entity.kind, operation.entity.meta.name, operation.entity.payload
        elif isinstance(operation, UpdateEntity):
            entity = index.get(operation.entity_id)
            payload = dict(entity.payload) if entity is not None else {}
            value = operation.field_patch.get("payload")
            if isinstance(value, Mapping):
                payload.update(value)
            name = str(operation.field_patch.get("name", entity.meta.name if entity else ""))
            yield entity.kind if entity is not None else None, name, payload


def validate(context: ValidationContext) -> None:
    for kind, name, payload in _payloads(context):
        if kind is EntityKind.REQUIREMENT and not str(payload.get("obligation", "")).strip():
            raise MethodologyValidationError("semantic_invalid", "requirement obligation is required")
        if kind is EntityKind.FUNCTION and _HARDWARE_WORDS.search(name):
            raise MethodologyValidationError("semantic_invalid", f"function name is solution-specific: {name}")
        if kind is EntityKind.VERIFICATION_CASE and not payload.get("fallback_placeholder"):
            if not str(payload.get("method", "")).strip() or not str(payload.get("pass_criteria", "")).strip():
                raise MethodologyValidationError("semantic_invalid", "verification case requires method and pass_criteria")
        if kind in {EntityKind.HAZARD, EntityKind.FAILURE_MODE} and not payload:
            raise MethodologyValidationError("semantic_invalid", f"{kind.value} payload is empty")
