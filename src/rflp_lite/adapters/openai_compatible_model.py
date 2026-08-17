"""Adapter for OpenAI-compatible chat completion endpoints."""

from __future__ import annotations

import json
import time
from collections.abc import Callable

from rflp_lite.adapters.llm_client import chat_completion
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import AdapterFailure
from rflp_lite.ports.generative_model import GenerationRequest, GenerationResponse


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
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1]).strip()
            if text.casefold().startswith("json"):
                text = text[4:].lstrip()
        try:
            value = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start:
                raise
            value = json.loads(text[start : end + 1])
        if not isinstance(value, dict):
            raise ValueError("LLM JSON response must be an object")
        return value

    def complete_json(self, request: GenerationRequest) -> GenerationResponse:
        started = time.monotonic()
        max_tokens = request.max_tokens
        local_cap = self._config.get("local_max_tokens")
        if str(self._config.get("kind", "")).casefold() == "local":
            try:
                if int(local_cap) > 0:
                    max_tokens = min(max_tokens, int(local_cap))
            except (TypeError, ValueError):
                pass
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
            payload = self._parse_json(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            repaired = True
            repair_messages = messages + [
                {"role": "assistant", "content": str(raw)},
                {"role": "user", "content": "上一个响应不是合法 JSON。只返回满足 schema 的 JSON 对象。"},
            ]
            try:
                repaired_raw = self._complete(
                    call_config, repair_messages, max_tokens=max_tokens
                )
                payload = self._parse_json(repaired_raw)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise AdapterFailure("LLM response is not valid JSON after one repair") from exc
            except Exception as exc:
                if isinstance(exc, AdapterFailure):
                    raise
                raise AdapterFailure("LLM repair completion failed") from exc
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
