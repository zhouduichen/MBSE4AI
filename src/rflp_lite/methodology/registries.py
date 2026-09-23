"""Executable registries used by the TaskSpec contract."""

from __future__ import annotations

from dataclasses import dataclass
import re
from importlib.resources import files
from typing import Any, Callable, Mapping

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import ContractViolation, MethodologyValidationError


Validator = Callable[[Any], None]


_PROMPT_VERSION = re.compile(r"(?:^|\.)v(?P<version>[0-9]+(?:\.[0-9]+)*)$")


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    template_id: str
    text: str
    version: str
    prompt_hash: str


class PromptRegistry:
    def __init__(self, templates: Mapping[str, str] | None = None):
        self._templates: dict[str, PromptTemplate] = {}
        for template_id, template in (templates or {}).items():
            self.register(template_id, template)

    def register(self, template_id: str, template: str, *, version: str | None = None) -> None:
        if not template_id.strip() or not template.strip():
            raise ValueError("prompt template id and value are required")
        prompt_text = str(template)
        prompt_version = version or _version_for(template_id)
        self._templates[template_id] = PromptTemplate(
            template_id, prompt_text, prompt_version, canonical_hash(prompt_text)
        )

    def resolve(self, template_id: str) -> PromptTemplate:
        """Resolve a prompt from an explicit registration or package resource.

        Resource ids intentionally omit the file's ``.md`` suffix.  Existing
        TaskSpecs use ids such as ``operational.system_definition`` and are
        resolved to ``system_definition.v1.md``.  A missing resource is a
        contract error rather than an opportunity to send a generic prompt.
        """

        clean_id = str(template_id).strip()
        if not clean_id:
            raise ContractViolation("prompt template id is required")
        registered = self._templates.get(clean_id)
        if registered is not None:
            return registered
        parts = clean_id.split(".")
        if len(parts) != 2:
            raise ContractViolation(f"prompt template is not registered: {clean_id}")
        phase, task_name = parts
        version = _version_for(clean_id)
        resource = files("rflp_lite").joinpath(
            "resources", "prompts", phase, f"{task_name}.{version}.md"
        )
        if not resource.is_file():
            raise ContractViolation(f"prompt template resource is missing: {clean_id}")
        try:
            prompt_text = resource.read_text(encoding="utf-8")
        except OSError as exc:
            raise ContractViolation(f"prompt template cannot be read: {clean_id}") from exc
        if not prompt_text.strip():
            raise ContractViolation(f"prompt template resource is empty: {clean_id}")
        resolved = PromptTemplate(clean_id, prompt_text, version, canonical_hash(prompt_text))
        self._templates[clean_id] = resolved
        return resolved

    def render(self, template_id: str, values: Mapping[str, object] | None = None) -> str:
        template = self.resolve(template_id).text
        try:
            return template.format_map({key: str(value) for key, value in (values or {}).items()})
        except (KeyError, ValueError) as exc:
            raise ContractViolation(f"prompt template cannot be rendered: {template_id}") from exc


def _version_for(template_id: str) -> str:
    match = _PROMPT_VERSION.search(str(template_id).strip())
    return f"v{match.group('version')}" if match else "v1"


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

    def validate(self, validator_ids: tuple[str, ...], value: Any = None, *, context: Any = None) -> None:
        subject = context if context is not None else value
        for validator_id in validator_ids:
            validator = self._validators.get(validator_id)
            if validator is None:
                raise ContractViolation(f"validator is not registered: {validator_id}")
            try:
                validator(subject)
            except ContractViolation:
                raise
            except MethodologyValidationError:
                # Preserve routable methodology codes such as
                # ``semantic_invalid`` for workflow-level repair/review
                # handling.  Wrapping these as ``validator_failed`` hides
                # the declared failure route from vertical generation.
                raise
            except Exception as exc:
                raise MethodologyValidationError("validator_failed", f"{validator_id}: {exc}") from exc


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 2
    backoff_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
