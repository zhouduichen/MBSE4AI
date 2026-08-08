from __future__ import annotations

import json
from urllib import error, request

from rflp_lite.domain.errors import AdapterFailure


def _endpoint(base_url: object) -> str:
    value = str(base_url or "").rstrip("/")
    return value if value.endswith("/chat/completions") else f"{value}/chat/completions"


def chat_completion(config: dict[str, object], messages: list[dict[str, str]], *, max_tokens: int | None = None) -> str:
    body: dict[str, object] = {
        "model": config["model"],
        "temperature": 0,
        "messages": messages,
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    headers = {"Content-Type": "application/json"}
    api_key = str(config.get("api_key", ""))
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    call = request.Request(
        _endpoint(config["base_url"]),
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with request.urlopen(call, timeout=int(config.get("timeout_seconds", 20))) as response:
            envelope = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        raise AdapterFailure(f"LLM 请求失败: HTTP {exc.code}") from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        raise AdapterFailure(f"LLM 请求失败: {type(exc).__name__}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdapterFailure("LLM 返回不是有效 JSON") from exc
    try:
        content = envelope["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AdapterFailure("LLM 返回缺少 choices.message.content") from exc
    if not isinstance(content, str):
        raise AdapterFailure("LLM 返回内容不是文本")
    return content


def test_connection(config: dict[str, object]) -> dict[str, object]:
    content = chat_completion(
        config,
        [{"role": "user", "content": "Reply with OK only."}],
        max_tokens=4,
    )
    return {
        "status": "connected",
        "provider": config.get("label", config.get("id", "LLM")),
        "model": config["model"],
        "base_url": config["base_url"],
        "preview": content.strip()[:80],
    }
