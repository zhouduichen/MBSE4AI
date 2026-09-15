from __future__ import annotations

import json
from urllib import error, request
from urllib.parse import urlparse
from typing import Mapping

from rflp_lite.domain.errors import AdapterFailure, TransportFailure
from rflp_lite.ports.token_budget import estimate_messages


# Provider tokenizers can count JSON punctuation, chat wrappers, and CJK text
# slightly differently from the model-independent estimate. Keep a bounded
# margin so a request that appears to fit locally does not cross the provider
# context limit by a handful of tokens.
_CONTEXT_TOKEN_SAFETY_MARGIN = 256


class _CompletionText(str):
    """Text response carrying the provider's completion stop reason."""

    def __new__(
        cls,
        value: str,
        done_reason: str = "",
        usage: Mapping[str, object] | None = None,
    ):
        result = str.__new__(cls, value)
        result.done_reason = done_reason
        result.usage = dict(usage or {})
        return result


def _endpoint(base_url: object) -> str:
    value = str(base_url or "").rstrip("/")
    return value if value.endswith("/chat/completions") else f"{value}/chat/completions"


def _text_content(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return ""


def _message_content(envelope: object) -> str:
    if not isinstance(envelope, dict):
        return ""
    native_message = envelope.get("message")
    if isinstance(native_message, dict):
        content = _text_content(native_message.get("content"))
        if content:
            return content
    choices = envelope.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return ""
    # Structured callers should receive the final answer in content. The
    # reasoning fallback keeps compatible providers usable when they return
    # the answer under reasoning_content instead.
    return (
        _text_content(message.get("content"))
        or _text_content(message.get("reasoning_content"))
        or _text_content(message.get("reasoning"))
    )


def _done_reason(envelope: object) -> str:
    if not isinstance(envelope, dict):
        return ""
    reason = envelope.get("done_reason")
    if isinstance(reason, str) and reason:
        return reason
    choices = envelope.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        reason = choices[0].get("finish_reason")
        if isinstance(reason, str):
            return reason
    return ""


def _usage(envelope: object) -> Mapping[str, object]:
    if not isinstance(envelope, dict):
        return {}
    value = envelope.get("usage")
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    native_keys = (
        "prompt_eval_count", "eval_count", "total_duration",
        "load_duration", "prompt_eval_duration", "eval_duration",
    )
    return {
        key: envelope[key]
        for key in native_keys
        if key in envelope
    }


def _provider_error_message(value: object) -> str:
    if isinstance(value, str):
        try:
            return _provider_error_message(json.loads(value))
        except json.JSONDecodeError:
            return value.strip()
    if isinstance(value, dict):
        message = value.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
        for key in ("error", "details", "cause"):
            detail = _provider_error_message(value.get(key))
            if detail:
                return detail
    return ""


def _is_native_ollama(config: dict[str, object]) -> bool:
    provider = str(config.get("provider", "")).casefold()
    if provider:
        return provider in {"ollama", "ollama-native"}
    base_url = str(config.get("base_url", "")).casefold()
    return str(config.get("kind", "")).casefold() == "local" and (
        "11434" in base_url or "ollama" in base_url
    )


def _native_ollama_endpoint(base_url: object) -> str:
    parsed = urlparse(str(base_url or "").rstrip("/"))
    if not parsed.scheme or not parsed.netloc:
        raise AdapterFailure("Ollama Base URL 无效")
    return f"{parsed.scheme}://{parsed.netloc}/api/chat"


def _bounded_max_tokens(
    config: dict[str, object], max_tokens: int | None
) -> int | None:
    """Apply a profile cap without increasing the caller's request budget."""

    configured = config.get("max_output_tokens", config.get("local_max_tokens", 0))
    try:
        cap = int(configured or 0)
    except (TypeError, ValueError):
        cap = 0
    if cap <= 0:
        return max_tokens
    if max_tokens is None:
        return cap
    return min(max_tokens, cap)


def _fit_context_window(
    config: Mapping[str, object],
    messages: list[dict[str, str]],
    max_tokens: int | None,
) -> int | None:
    """Keep provider input plus output inside the configured context window."""

    if max_tokens is None:
        return None
    try:
        context_window = int(
            config.get("context_window", config.get("local_context_tokens", 0))
            or 0
        )
    except (TypeError, ValueError):
        context_window = 0
    if context_window <= 0:
        return max_tokens
    available = (
        context_window
        - estimate_messages(messages)
        - _CONTEXT_TOKEN_SAFETY_MARGIN
    )
    if available < 256:
        raise TransportFailure(
            "LLM prompt exceeds the configured context window",
            code="context_window_exceeded",
            provider_id=str(config.get("provider", config.get("id", ""))),
            model_id=str(config.get("model", "")),
        )
    return min(max_tokens, available)


def _sampling_value(config: dict[str, object], name: str, default: float) -> float:
    try:
        value = float(config.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def _seed_value(config: dict[str, object]) -> int | None:
    try:
        value = config.get("seed")
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def chat_completion(config: dict[str, object], messages: list[dict[str, str]], *, max_tokens: int | None = None) -> str:
    max_tokens = _bounded_max_tokens(config, max_tokens)
    native_ollama = _is_native_ollama(config)
    if native_ollama:
        body: dict[str, object] = {
            "model": config["model"],
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {"temperature": _sampling_value(config, "temperature", 0.0)},
        }
        if max_tokens is not None:
            body["options"]["num_predict"] = max_tokens  # type: ignore[index]
        try:
            local_context_tokens = int(
                config.get("context_window", config.get("local_context_tokens", 0)) or 0
            )
        except (TypeError, ValueError):
            local_context_tokens = 0
        if local_context_tokens > 0:
            body["options"]["num_ctx"] = local_context_tokens  # type: ignore[index]
        seed = _seed_value(config)
        if seed is not None:
            body["options"]["seed"] = seed  # type: ignore[index]
        response_format = config.get("response_format")
        schema = config.get("json_schema")
        if isinstance(schema, dict):
            body["format"] = schema
        elif isinstance(response_format, dict):
            response_schema = response_format.get("json_schema")
            body["format"] = response_schema if isinstance(response_schema, dict) else "json"
        endpoint = _native_ollama_endpoint(config["base_url"])
    else:
        body = {
            "model": config["model"],
            "temperature": _sampling_value(config, "temperature", 0.0),
            "messages": messages,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        seed = _seed_value(config)
        if seed is not None:
            body["seed"] = seed
        response_format = config.get("response_format")
        if isinstance(response_format, dict):
            body["response_format"] = response_format
        endpoint = _endpoint(config["base_url"])
    thinking = config.get("thinking")
    if not native_ollama and isinstance(thinking, dict):
        body["thinking"] = thinking
    if not native_ollama and isinstance(config.get("think"), bool):
        body["think"] = config["think"]
    if not native_ollama and isinstance(config.get("reasoning_effort"), (str, dict)):
        body["reasoning_effort"] = config["reasoning_effort"]
    headers = {"Content-Type": "application/json"}
    api_key = str(config.get("api_key", ""))
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    call = request.Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with request.urlopen(call, timeout=int(config.get("timeout_seconds", 300))) as response:
            envelope = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = ""
        try:
            raw_detail = exc.read().decode("utf-8", "replace")
            payload = json.loads(raw_detail)
            error_payload = payload.get("error") if isinstance(payload, dict) else payload
            detail = _provider_error_message(error_payload)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            detail = ""
        suffix = f": {detail}" if detail else ""
        raise TransportFailure(
            f"LLM 请求失败: HTTP {exc.code}{suffix}",
            code="http_error",
            provider_id=str(config.get("provider", "")),
            model_id=str(config.get("model", "")),
        ) from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        raise TransportFailure(
            f"LLM 请求失败: {type(exc).__name__}",
            code="network_error",
            provider_id=str(config.get("provider", "")),
            model_id=str(config.get("model", "")),
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdapterFailure("LLM 返回不是有效 JSON") from exc
    return _CompletionText(
        _message_content(envelope),
        _done_reason(envelope),
        _usage(envelope),
    )


def test_connection(config: dict[str, object]) -> dict[str, object]:
    test_config = dict(config)
    provider = str(test_config.get("provider", "")).casefold() or (
        "ollama" if _is_native_ollama(test_config) else "openai-compatible"
    )
    provider_text = f'{test_config.get("base_url", "")} {test_config.get("model", "")}'.casefold()
    is_ollama = provider == "ollama"
    if provider == "openai-compatible" and str(test_config.get("kind", "")).casefold() == "remote" and not str(test_config.get("api_key", "")).strip():
        raise AdapterFailure("远程 LLM 缺少 API Key")
    if "deepseek" in provider_text:
        test_config["thinking"] = {"type": "disabled"}
    if is_ollama:
        test_config["reasoning_effort"] = "none"
    content = chat_completion(
        test_config,
        [{"role": "user", "content": "Reply with OK only."}],
        max_tokens=16,
    )
    text = str(content).strip()
    if not text:
        return {
            "connected": False,
            "connection_status": "invalid_response",
            "message": "模型返回为空",
        }
    return {
        "connected": True,
        "connection_status": "connected",
        "status": "connected",
        "provider": config.get("label", config.get("id", "LLM")),
        "provider_id": provider,
        "model": config["model"],
        "base_url": config["base_url"],
        "message": "模型已返回响应",
        "preview": text[:80],
    }
