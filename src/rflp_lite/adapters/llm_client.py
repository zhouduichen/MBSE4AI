from __future__ import annotations

import json
from urllib import error, request
from urllib.parse import urlparse

from rflp_lite.domain.errors import AdapterFailure


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


def _is_native_ollama(config: dict[str, object]) -> bool:
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
    """Apply a local profile cap without increasing the caller's budget."""

    if str(config.get("kind", "")).casefold() != "local":
        return max_tokens
    try:
        local_cap = int(config.get("local_max_tokens", 0))
    except (TypeError, ValueError):
        return max_tokens
    if local_cap <= 0:
        return max_tokens
    if max_tokens is None:
        return local_cap
    return min(max_tokens, local_cap)


def chat_completion(config: dict[str, object], messages: list[dict[str, str]], *, max_tokens: int | None = None) -> str:
    max_tokens = _bounded_max_tokens(config, max_tokens)
    native_ollama = _is_native_ollama(config)
    if native_ollama:
        body: dict[str, object] = {
            "model": config["model"],
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {"temperature": 0},
        }
        if max_tokens is not None:
            body["options"]["num_predict"] = max_tokens  # type: ignore[index]
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
            "temperature": 0,
            "messages": messages,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
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
            error_payload = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(error_payload, dict):
                detail = str(error_payload.get("message", "")).strip()
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            detail = ""
        suffix = f": {detail}" if detail else ""
        raise AdapterFailure(f"LLM 请求失败: HTTP {exc.code}{suffix}") from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        raise AdapterFailure(f"LLM 请求失败: {type(exc).__name__}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdapterFailure("LLM 返回不是有效 JSON") from exc
    return _message_content(envelope)


def test_connection(config: dict[str, object]) -> dict[str, object]:
    test_config = dict(config)
    provider_text = f'{test_config.get("base_url", "")} {test_config.get("model", "")}'.casefold()
    is_ollama = "11434" in provider_text or "ollama" in provider_text
    if "deepseek" in provider_text:
        test_config["thinking"] = {"type": "disabled"}
    if is_ollama:
        test_config["reasoning_effort"] = "none"
    content = chat_completion(
        test_config,
        [{"role": "user", "content": "Reply with OK only."}],
        max_tokens=16,
    )
    return {
        "status": "connected",
        "provider": config.get("label", config.get("id", "LLM")),
        "model": config["model"],
        "base_url": config["base_url"],
        "preview": content.strip()[:80],
    }
