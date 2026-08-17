from __future__ import annotations

import json
from io import BytesIO
from urllib.error import HTTPError

from rflp_lite.adapters import llm_client
from rflp_lite.domain.errors import AdapterFailure


class _Response:
    def __init__(self, payload=None):
        self.payload = payload or {"choices": [{"message": {"content": "OK"}}]}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


def test_chat_completion_uses_openai_compatible_endpoint(monkeypatch):
    captured = {}

    def fake_urlopen(call, timeout):
        captured["url"] = call.full_url
        captured["headers"] = dict(call.header_items())
        captured["timeout"] = timeout
        captured["body"] = json.loads(call.data.decode())
        return _Response()

    monkeypatch.setattr(llm_client.request, "urlopen", fake_urlopen)
    content = llm_client.chat_completion(
        {
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen-local",
            "api_key": "local-key",
            "timeout_seconds": 7,
        },
        [{"role": "user", "content": "ping"}],
    )

    assert content == "OK"
    assert captured["url"] == "http://127.0.0.1:11434/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer local-key"
    assert captured["timeout"] == 7


def test_chat_completion_sends_structured_deepseek_options(monkeypatch):
    captured = {}

    def fake_urlopen(call, timeout):
        captured["body"] = json.loads(call.data.decode())
        return _Response()

    monkeypatch.setattr(llm_client.request, "urlopen", fake_urlopen)
    llm_client.chat_completion(
        {
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-flash",
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "timeout_seconds": 300,
        },
        [{"role": "user", "content": "json"}],
    )

    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["thinking"] == {"type": "disabled"}


def test_chat_completion_sends_ollama_reasoning_control(monkeypatch):
    captured = {}

    def fake_urlopen(call, timeout):
        captured["body"] = json.loads(call.data.decode())
        return _Response()

    monkeypatch.setattr(llm_client.request, "urlopen", fake_urlopen)
    llm_client.chat_completion(
        {
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen3.5:9b",
            "reasoning_effort": "none",
        },
        [{"role": "user", "content": "json"}],
    )

    assert captured["body"]["reasoning_effort"] == "none"


def test_chat_completion_sends_ollama_think_flag(monkeypatch):
    captured = {}

    def fake_urlopen(call, timeout):
        captured["body"] = json.loads(call.data.decode())
        return _Response()

    monkeypatch.setattr(llm_client.request, "urlopen", fake_urlopen)
    llm_client.chat_completion(
        {
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen3.5:9b",
            "think": False,
        },
        [{"role": "user", "content": "json"}],
    )

    assert captured["body"]["think"] is False


def test_local_ollama_uses_native_chat_to_disable_reasoning(monkeypatch):
    captured = {}

    def fake_urlopen(call, timeout):
        captured["url"] = call.full_url
        captured["body"] = json.loads(call.data.decode())
        captured["timeout"] = timeout
        return _Response({"message": {"content": '{"items": []}'}})

    monkeypatch.setattr(llm_client.request, "urlopen", fake_urlopen)
    content = llm_client.chat_completion(
        {
            "kind": "local",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen3.5:9b",
            "response_format": {"type": "json_object"},
            "timeout_seconds": 300,
        },
        [{"role": "user", "content": "json"}],
        max_tokens=5200,
    )

    assert content == '{"items": []}'
    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert captured["body"]["think"] is False
    assert captured["body"]["stream"] is False
    assert captured["body"]["format"] == "json"
    assert captured["body"]["options"]["num_predict"] == 5200


def test_native_ollama_uses_supplied_json_schema(monkeypatch):
    captured = {}

    def fake_urlopen(call, timeout):
        captured["body"] = json.loads(call.data.decode())
        return _Response({"message": {"content": '{"items": []}'}})

    monkeypatch.setattr(llm_client.request, "urlopen", fake_urlopen)
    schema = {"type": "object", "required": ["items"]}
    llm_client.chat_completion(
        {
            "kind": "local",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen3.5:9b",
            "response_format": {"type": "json_object"},
            "json_schema": schema,
        },
        [{"role": "user", "content": "json"}],
    )

    assert captured["body"]["format"] == schema


def test_chat_completion_falls_back_to_reasoning_content(monkeypatch):
    def fake_urlopen(_call, timeout):
        assert timeout == 300
        return _Response(
            {"choices": [{"message": {"content": "", "reasoning_content": '{"items": []}'}}]}
        )

    monkeypatch.setattr(llm_client.request, "urlopen", fake_urlopen)
    content = llm_client.chat_completion(
        {"base_url": "http://127.0.0.1:1234/v1", "model": "local"},
        [{"role": "user", "content": "json"}],
    )

    assert content == '{"items": []}'


def test_chat_completion_surfaces_provider_error_detail(monkeypatch):
    def fake_urlopen(_call, timeout):
        assert timeout == 300
        raise HTTPError(
            "https://example.test/chat/completions",
            402,
            "payment required",
            {},
            BytesIO(b'{"error":{"message":"Insufficient Balance"}}'),
        )

    monkeypatch.setattr(llm_client.request, "urlopen", fake_urlopen)
    try:
        llm_client.chat_completion(
            {"base_url": "https://example.test", "model": "model"},
            [{"role": "user", "content": "json"}],
        )
    except AdapterFailure as exc:
        assert str(exc) == "LLM 请求失败: HTTP 402: Insufficient Balance"
    else:
        raise AssertionError("expected provider error")
