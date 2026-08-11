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

    def complete_json(self, request: GenerationRequest) -> GenerationResponse:
        started = time.monotonic()
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
        try:
            raw = self._complete(self._config, messages, max_tokens=request.max_tokens)
        except Exception as exc:
            if isinstance(exc, AdapterFailure):
                raise
            raise AdapterFailure("LLM completion failed") from exc
        repaired = False
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            repaired = True
            repair_messages = messages + [
                {"role": "assistant", "content": str(raw)},
                {"role": "user", "content": "上一个响应不是合法 JSON。只返回满足 schema 的 JSON 对象。"},
            ]
            try:
                repaired_raw = self._complete(
                    self._config, repair_messages, max_tokens=request.max_tokens
                )
                payload = json.loads(repaired_raw)
            except (TypeError, json.JSONDecodeError) as exc:
                raise AdapterFailure("LLM response is not valid JSON after one repair") from exc
            except Exception as exc:
                if isinstance(exc, AdapterFailure):
                    raise
                raise AdapterFailure("LLM repair completion failed") from exc
        if not isinstance(payload, dict):
            raise AdapterFailure("LLM JSON response must be an object")
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
