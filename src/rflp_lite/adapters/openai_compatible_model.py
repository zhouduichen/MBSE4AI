"""Adapter for OpenAI-compatible chat completion endpoints."""

from __future__ import annotations

import json
import time
from collections.abc import Callable

from rflp_lite.adapters.llm_client import (
    _bounded_max_tokens,
    _fit_context_window,
    _is_native_ollama,
    chat_completion,
)
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import AdapterFailure, StructuredOutputFailure, TransportFailure
from rflp_lite.ports.generative_model import (
    GenerationRequest,
    GenerationResponse,
    add_simplified_chinese_instruction,
)


_REPAIR_FAILURE = "LLM response is not valid JSON after one repair"


class _InvalidStructuredResponse(ValueError):
    """The provider returned JSON that cannot be accepted for this request."""

    def __init__(self, message: str, *, code: str = "schema_validation") -> None:
        self.code = code
        super().__init__(message)


def _ollama_transport_schema(value: object) -> object:
    """Compile a provider-safe copy without weakening application validation.

    Ollama 0.32.x rejects a grammar containing ``maxLength: 2000`` even though
    the same object schema is valid JSON Schema.  The canonical schema remains
    on the request and is still used for post-response validation; only the
    native Ollama grammar copy omits that provider-only constraint.
    """

    if isinstance(value, dict):
        return {
            str(key): _ollama_transport_schema(item)
            for key, item in value.items()
            if not (
                key == "maxLength"
                and isinstance(item, int)
                and item >= 2000
            )
        }
    if isinstance(value, list):
        return [_ollama_transport_schema(item) for item in value]
    return value


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
    def _parse_json(raw: object) -> object:
        text = str(raw or "").strip()
        if not text:
            raise _InvalidStructuredResponse("empty content", code="json_decode")
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) < 3 or not lines[-1].strip().startswith("```"):
                raise _InvalidStructuredResponse("unclosed JSON fence", code="json_decode")
            text = "\n".join(lines[1:-1]).strip()
            if text.casefold().startswith("json"):
                text = text[4:].lstrip()
        try:
            value = json.loads(text)
        except (TypeError, json.JSONDecodeError) as exc:
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start:
                raise _InvalidStructuredResponse("no complete JSON object", code="json_decode") from exc
            try:
                value = json.loads(text[start : end + 1])
            except (TypeError, json.JSONDecodeError) as boundary_exc:
                raise _InvalidStructuredResponse("invalid JSON object", code="json_decode") from boundary_exc
        return value

    @classmethod
    def _parse_and_validate(
        cls, raw: object, response_schema: dict[str, object]
    ) -> dict[str, object]:
        payload = cls._parse_json(raw)
        # Keep the older requirements/ai provider shape usable while the
        # application still receives the strict object envelope.  This is
        # deliberately limited to schemas whose only contract is an `items`
        # array; six-block schemas still require their full envelope.
        if isinstance(payload, list) and response_schema.get("type") == "object":
            properties = response_schema.get("properties")
            required = response_schema.get("required")
            if isinstance(properties, dict) and set(properties) == {"items"} and required == ["items"]:
                payload = {"items": payload}
        if not isinstance(payload, dict):
            raise _InvalidStructuredResponse("response must be an object", code="schema_validation")
        try:
            import jsonschema
        except ImportError as exc:
            raise AdapterFailure("JSON schema validation is unavailable") from exc
        try:
            jsonschema.validate(instance=payload, schema=response_schema)
        except jsonschema.ValidationError as exc:
            raise _InvalidStructuredResponse("response does not match schema", code="schema_validation") from exc
        except jsonschema.SchemaError as exc:
            raise AdapterFailure("LLM response schema is invalid") from exc
        return payload

    @staticmethod
    def _ensure_complete(raw: object) -> None:
        if str(getattr(raw, "done_reason", "")).casefold() in {"length", "max_tokens"}:
            raise _InvalidStructuredResponse("provider output was truncated", code="truncated")

    def _repair_budget(self, max_tokens: int | None, raw: object) -> int | None:
        if max_tokens is None:
            return None
        if str(getattr(raw, "done_reason", "")).casefold() not in {"length", "max_tokens"}:
            return max_tokens
        try:
            local_cap = int(
                self._config.get(
                    "max_output_tokens",
                    self._config.get("local_max_tokens", 0),
                )
                or 0
            )
        except (TypeError, ValueError):
            local_cap = 0
        expanded = max_tokens * 2
        return min(local_cap, expanded) if local_cap > max_tokens else max_tokens

    @staticmethod
    def _repair_messages(
        request: GenerationRequest, raw: object, *, include_schema: bool = True
    ) -> list[dict[str, str]]:
        max_items = request.user_payload.get("max_items")
        if not isinstance(max_items, int) or max_items < 1:
            max_items = 8
        envelope = {
            "input": request.user_payload,
            "invalid_response": str(raw or "")[:6000],
        }
        if include_schema:
            envelope["response_schema"] = request.response_schema
        return [
            {
                "role": "system",
                "content": add_simplified_chinese_instruction(
                    f"重新生成完整的 JSON 分析结果，最多返回 {max_items} 项；"
                    "保留有效内容，修复 TaskProposal 结构，不要解释，也不要用空数组规避任务。"
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
        native_ollama = _is_native_ollama(self._config)
        prompt_payload: dict[str, object] = {"input": request.user_payload}
        if not native_ollama:
            # Native Ollama receives the schema through `format`; repeating it
            # in the prompt wastes context tokens and can cause local output
            # truncation on a 4B model.
            prompt_payload["response_schema"] = request.response_schema
        messages = [
            {
                "role": "system",
                "content": add_simplified_chinese_instruction(request.system_prompt),
            },
            {
                "role": "user",
                "content": json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True),
            },
        ]
        max_tokens = _fit_context_window(self._config, messages, max_tokens)
        call_config = dict(self._config)
        structured_output_mode = str(
            call_config.get("structured_output_mode", "json_schema")
        ).casefold()
        if native_ollama:
            if structured_output_mode != "none":
                call_config["json_schema"] = (
                    _ollama_transport_schema(request.response_schema)
                )
        elif str(call_config.get("kind", "")).casefold() == "local":
            call_config["json_schema"] = request.response_schema
        elif str(call_config.get("structured_output_mode", "json_schema")).casefold() != "none":
            call_config.setdefault(
                "response_format",
                {
                    "type": "json_schema",
                    "json_schema": {
                        "name": request.lens_id.replace("-", "_"),
                        "strict": True,
                        "schema": request.response_schema,
                    },
                },
            )
        try:
            raw = self._complete(call_config, messages, max_tokens=max_tokens)
        except Exception as exc:
            if isinstance(exc, AdapterFailure):
                raise
            raise TransportFailure(
                "LLM completion failed",
                code="completion_failed",
                provider_id=str(self._config.get("id", self._config.get("provider", ""))),
                model_id=str(self._config.get("model", "")),
            ) from exc
        repaired = False
        final_raw = raw
        try:
            self._ensure_complete(raw)
            payload = self._parse_and_validate(raw, request.response_schema)
        except _InvalidStructuredResponse:
            repaired = True
            try:
                repaired_raw = self._complete(
                    call_config,
                    repair_messages := self._repair_messages(
                        request, raw, include_schema=not native_ollama
                    ),
                    max_tokens=_fit_context_window(
                        self._config,
                        repair_messages,
                        self._repair_budget(max_tokens, raw),
                    ),
                )
                self._ensure_complete(repaired_raw)
                payload = self._parse_and_validate(
                    repaired_raw, request.response_schema
                )
                final_raw = repaired_raw
            except _InvalidStructuredResponse as exc:
                raise StructuredOutputFailure(
                    _REPAIR_FAILURE,
                    code=exc.code,
                    raw_response=str(repaired_raw or ""),
                    initial_raw_response=str(raw or ""),
                    schema_hash=canonical_hash(request.response_schema),
                    retry_count=1,
                    provider_id=str(self._config.get("id", self._config.get("label", "openai-compatible"))),
                    model_id=str(self._config.get("model", "")),
                    finish_reason=str(getattr(repaired_raw, "done_reason", "")),
                    usage=getattr(repaired_raw, "usage", {}),
                ) from exc
            except TransportFailure as exc:
                raise TransportFailure(
                    str(exc),
                    code=exc.code,
                    provider_id=exc.provider_id or str(self._config.get("id", self._config.get("label", "openai-compatible"))),
                    model_id=exc.model_id or str(self._config.get("model", "")),
                    raw_response=str(raw or ""),
                    initial_raw_response=str(raw or ""),
                    schema_hash=canonical_hash(request.response_schema),
                    retry_count=1,
                ) from exc
            except Exception as exc:
                if isinstance(exc, AdapterFailure):
                    raise
                raise TransportFailure(
                    _REPAIR_FAILURE,
                    provider_id=str(self._config.get("id", self._config.get("label", "openai-compatible"))),
                    model_id=str(self._config.get("model", "")),
                    code="structural_retry_transport",
                    raw_response=str(raw or ""),
                    initial_raw_response=str(raw or ""),
                    schema_hash=canonical_hash(request.response_schema),
                    retry_count=1,
                ) from exc
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
            finish_reason=str(getattr(final_raw, "done_reason", "")),
            usage=getattr(final_raw, "usage", {}),
        )
