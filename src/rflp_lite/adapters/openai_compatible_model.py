"""Adapter for OpenAI-compatible chat completion endpoints."""

from __future__ import annotations

import json
import time
from collections.abc import Callable

from rflp_lite.adapters.llm_client import _bounded_max_tokens, chat_completion
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import AdapterFailure
from rflp_lite.ports.generative_model import GenerationRequest, GenerationResponse


_REPAIR_MAX_TOKENS = 512
_REPAIR_FAILURE = "LLM response is not valid JSON after one repair"


class _InvalidStructuredResponse(ValueError):
    """The provider returned JSON that cannot be accepted for this request."""


class OpenAICompatibleModel:
    """Translate the stable application request into one JSON-only model call."""

    def __init__(
        self,
        config: dict[str, object],
        *,
        complete: Callable[..., str] = chat_completion,
    ) -> None:
        self._config = dict(config)
        self._complete = complete

    @staticmethod
    def _parse_json(raw: object) -> dict[str, object]:
        text = str(raw or "").strip()
        if not text:
            raise _InvalidStructuredResponse("empty content")
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) < 3 or not lines[-1].strip().startswith("```"):
                raise _InvalidStructuredResponse("unclosed JSON fence")
            text = "\n".join(lines[1:-1]).strip()
            if text.casefold().startswith("json"):
                text = text[4:].lstrip()
        try:
            value = json.loads(text)
        except (TypeError, json.JSONDecodeError) as exc:
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start:
                raise _InvalidStructuredResponse("no complete JSON object") from exc
            try:
                value = json.loads(text[start : end + 1])
            except (TypeError, json.JSONDecodeError) as boundary_exc:
                raise _InvalidStructuredResponse("invalid JSON object") from boundary_exc
        if not isinstance(value, dict):
            raise _InvalidStructuredResponse("response must be an object")
        return value

    @classmethod
    def _parse_and_validate(
        cls, raw: object, response_schema: dict[str, object]
    ) -> dict[str, object]:
        payload = cls._parse_json(raw)
        try:
            import jsonschema
        except ImportError as exc:
            raise AdapterFailure("JSON schema validation is unavailable") from exc
        try:
            jsonschema.validate(instance=payload, schema=response_schema)
        except jsonschema.ValidationError as exc:
            raise _InvalidStructuredResponse("response does not match schema") from exc
        except jsonschema.SchemaError as exc:
            raise AdapterFailure("LLM response schema is invalid") from exc
        return payload

    @staticmethod
    def _repair_messages(
        request: GenerationRequest, raw: object
    ) -> list[dict[str, str]]:
        max_items = request.user_payload.get("max_items")
        if not isinstance(max_items, int) or max_items < 1:
            max_items = 8
        envelope = {
            "input": request.user_payload,
            "response_schema": request.response_schema,
            "invalid_response": str(raw or "")[:6000],
        }
        return [
            {
                "role": "system",
                "content": (
                    f"只修复 JSON 结构，最多返回 {max_items} 项，不要解释；"
                    "缺失内容返回空数组。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(envelope, ensure_ascii=False, sort_keys=True),
            },
        ]

    def complete_json(self, request: GenerationRequest) -> GenerationResponse:
        started = time.monotonic()
        max_tokens = _bounded_max_tokens(self._config, request.max_tokens)
        messages = [
            {"role": "system", "content": request.system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {"input": request.user_payload, "response_schema": request.response_schema},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
        ]
        call_config = dict(self._config)
        if str(call_config.get("kind", "")).casefold() == "local":
            call_config["json_schema"] = request.response_schema
        try:
            raw = self._complete(call_config, messages, max_tokens=max_tokens)
        except Exception as exc:
            if isinstance(exc, AdapterFailure):
                raise
            raise AdapterFailure("LLM completion failed") from exc
        repaired = False
        try:
            payload = self._parse_and_validate(raw, request.response_schema)
        except _InvalidStructuredResponse:
            repaired = True
            try:
                repaired_raw = self._complete(
                    call_config,
                    self._repair_messages(request, raw),
                    max_tokens=(
                        _REPAIR_MAX_TOKENS
                        if max_tokens is None
                        else min(max_tokens, _REPAIR_MAX_TOKENS)
                    ),
                )
                payload = self._parse_and_validate(
                    repaired_raw, request.response_schema
                )
            except Exception as exc:
                raise AdapterFailure(_REPAIR_FAILURE) from exc
        return GenerationResponse(
            lens_id=request.lens_id,
            payload=payload,
            input_hash=canonical_hash((request.lens_id, request.user_payload, request.response_schema)),
            output_hash=canonical_hash(payload),
            repaired=repaired,
            provider_id=str(self._config.get("id", self._config.get("label", "openai-compatible"))),
            model_id=str(self._config.get("model", "")),
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            status="completed",
        )
