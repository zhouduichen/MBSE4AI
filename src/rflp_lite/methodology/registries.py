"""Executable registries used by the TaskSpec contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from rflp_lite.domain.errors import ContractViolation


Validator = Callable[[Any], None]


class PromptRegistry:
    def __init__(self, templates: Mapping[str, str] | None = None):
        self._templates = dict(templates or {})

    def register(self, template_id: str, template: str) -> None:
        if not template_id.strip() or not template.strip():
            raise ValueError("prompt template id and value are required")
        self._templates[template_id] = template

    def render(self, template_id: str, values: Mapping[str, object] | None = None) -> str:
        template = self._templates.get(template_id, template_id)
        try:
            return template.format_map({key: str(value) for key, value in (values or {}).items()})
        except (KeyError, ValueError) as exc:
            raise ContractViolation(f"prompt template cannot be rendered: {template_id}") from exc


class SchemaRegistry:
    def __init__(self, schemas: Mapping[str, Mapping[str, object]] | None = None):
        self._schemas = {key: dict(value) for key, value in (schemas or {}).items()}

    def register(self, schema_id: str, schema: Mapping[str, object]) -> None:
        self._schemas[schema_id] = dict(schema)

    def get(self, schema_id: str) -> dict[str, object]:
        try:
            return dict(self._schemas[schema_id])
        except KeyError as exc:
            raise ContractViolation(f"schema is not registered: {schema_id}") from exc


class ValidatorRegistry:
    def __init__(self, validators: Mapping[str, Validator] | None = None):
        self._validators = dict(validators or {})

    def register(self, validator_id: str, validator: Validator) -> None:
        self._validators[validator_id] = validator

    def validate(self, validator_ids: tuple[str, ...], value: Any) -> None:
        for validator_id in validator_ids:
            validator = self._validators.get(validator_id)
            if validator is None:
                raise ContractViolation(f"validator is not registered: {validator_id}")
            try:
                validator(value)
            except ContractViolation:
                raise
            except Exception as exc:
                raise ContractViolation(f"validator failed: {validator_id}: {exc}") from exc


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 2
    backoff_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
