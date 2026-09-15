from __future__ import annotations

import json
from io import BytesIO
from urllib.error import HTTPError

import pytest

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


def test_chat_completion_sends_schema_to_openai_compatible_ssh_endpoint(monkeypatch):
    captured = {}

    def fake_urlopen(call, timeout):
        captured["body"] = json.loads(call.data.decode())
        return _Response()

    monkeypatch.setattr(llm_client.request, "urlopen", fake_urlopen)
    llm_client.chat_completion(
        {
            "kind": "local",
            "provider": "openai-compatible",
            "base_url": "http://127.0.0.1:18000/v1",
            "model": "qwen3.5-controller",
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "task",
                    "strict": True,
                    "schema": {"type": "object", "required": ["items"]},
                },
            },
        },
        [{"role": "user", "content": "json"}],
    )

    assert captured["body"]["response_format"]["type"] == "json_schema"
    assert captured["body"]["response_format"]["json_schema"]["strict"] is True


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


def test_chat_completion_sends_remote_reasoning_controls(monkeypatch):
    captured = {}

    def fake_urlopen(call, timeout):
        captured["body"] = json.loads(call.data.decode())
        return _Response()

    monkeypatch.setattr(llm_client.request, "urlopen", fake_urlopen)
    llm_client.chat_completion(
        {
            "base_url": "http://127.0.0.1:18000/v1",
            "model": "qwen3.5-controller",
            "reasoning_effort": "none",
            "think": False,
        },
        [{"role": "user", "content": "json"}],
    )

    assert captured["body"]["reasoning_effort"] == "none"
    assert captured["body"]["think"] is False


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


def test_native_ollama_think_flag_cannot_be_enabled_by_profile(monkeypatch):
    captured = {}

    def fake_urlopen(call, timeout):
        captured["body"] = json.loads(call.data.decode())
        return _Response({"message": {"content": '{"items": []}'}})

    monkeypatch.setattr(llm_client.request, "urlopen", fake_urlopen)
    llm_client.chat_completion(
        {
            "kind": "local",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen3.5:4b",
            "think": True,
            "thinking": {"type": "enabled"},
        },
        [{"role": "user", "content": "json"}],
    )

    assert captured["body"]["think"] is False
    assert "thinking" not in captured["body"]


def test_chat_completion_uses_smaller_local_token_budget(monkeypatch):
    captured = {}

    def fake_urlopen(call, timeout):
        captured["body"] = json.loads(call.data.decode())
        return _Response({"message": {"content": '{"items": []}'}})

    monkeypatch.setattr(llm_client.request, "urlopen", fake_urlopen)
    llm_client.chat_completion(
        {
            "kind": "local",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen3.5:4b",
            "local_max_tokens": 600,
        },
        [{"role": "user", "content": "json"}],
        max_tokens=1200,
    )

    assert captured["body"]["options"]["num_predict"] == 600


def test_native_ollama_sends_explicit_context_budget(monkeypatch):
    captured = {}

    def fake_urlopen(call, timeout):
        captured["body"] = json.loads(call.data.decode())
        return _Response({"message": {"content": '{"items": []}'}})

    monkeypatch.setattr(llm_client.request, "urlopen", fake_urlopen)
    llm_client.chat_completion(
        {
            "kind": "local",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen3.5:4b",
            "local_context_tokens": 8192,
        },
        [{"role": "user", "content": "json"}],
    )

    assert captured["body"]["options"]["num_ctx"] == 8192


def test_native_ollama_uses_profile_sampling_controls_and_usage(monkeypatch):
    captured = {}

    def fake_urlopen(call, timeout):
        captured["body"] = json.loads(call.data.decode())
        return _Response({
            "message": {"content": '{"items": []}'},
            "done_reason": "stop",
            "prompt_eval_count": 12,
            "eval_count": 7,
        })

    monkeypatch.setattr(llm_client.request, "urlopen", fake_urlopen)
    content = llm_client.chat_completion(
        {
            "kind": "local",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen3.5:9b",
            "context_window": 8192,
            "temperature": 0.2,
            "seed": 42,
        },
        [{"role": "user", "content": "json"}],
    )

    assert content == '{"items": []}'
    assert captured["body"]["options"]["temperature"] == 0.2
    assert captured["body"]["options"]["seed"] == 42
    assert content.done_reason == "stop"
    assert content.usage == {"prompt_eval_count": 12, "eval_count": 7}


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


def test_chat_completion_preserves_completion_stop_reason(monkeypatch):
    def fake_urlopen(_call, timeout):
        return _Response(
            {"message": {"content": '{"items": ['}, "done_reason": "length"}
        )

    monkeypatch.setattr(llm_client.request, "urlopen", fake_urlopen)
    content = llm_client.chat_completion(
        {"base_url": "http://127.0.0.1:11434/v1", "model": "qwen"},
        [{"role": "user", "content": "json"}],
    )

    assert content == '{"items": ['
    assert content.done_reason == "length"


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


def test_chat_completion_surfaces_nested_ollama_error_detail(monkeypatch):
    def fake_urlopen(_call, timeout):
        raise HTTPError(
            "http://127.0.0.1:11434/api/chat",
            400,
            "bad request",
            {},
            BytesIO(
                json.dumps(
                    {"error": json.dumps({"error": {"message": "failed to parse grammar"}})}
                ).encode()
            ),
        )

    monkeypatch.setattr(llm_client.request, "urlopen", fake_urlopen)
    with pytest.raises(AdapterFailure, match="failed to parse grammar"):
        llm_client.chat_completion(
            {"base_url": "http://127.0.0.1:11434/v1", "model": "qwen"},
            [{"role": "user", "content": "json"}],
        )


def test_explicit_ollama_provider_uses_native_endpoint_for_remote_host(monkeypatch):
    captured = {}

    def fake_urlopen(call, timeout):
        captured["url"] = call.full_url
        captured["body"] = json.loads(call.data.decode())
        return _Response({"message": {"content": "OK"}})

    monkeypatch.setattr(llm_client.request, "urlopen", fake_urlopen)
    result = llm_client.test_connection(
        {
            "provider": "ollama",
            "kind": "remote",
            "base_url": "http://10.0.0.8:11434/v1",
            "model": "qwen3.5:9b",
        }
    )

    assert captured["url"] == "http://10.0.0.8:11434/api/chat"
    assert captured["body"]["stream"] is False
    assert result["connection_status"] == "connected"
    assert result["provider_id"] == "ollama"


def test_openai_compatible_connection_requires_key_for_remote_profile(monkeypatch):
    def fail_urlopen(*_args, **_kwargs):
        raise AssertionError("network should not be called")

    monkeypatch.setattr(llm_client.request, "urlopen", fail_urlopen)
    with pytest.raises(AdapterFailure, match="缺少 API Key"):
        llm_client.test_connection(
            {
                "provider": "openai-compatible",
                "kind": "remote",
                "base_url": "https://api.example.test/v1",
                "model": "model",
            }
        )
