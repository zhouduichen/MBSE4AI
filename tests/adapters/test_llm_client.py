from __future__ import annotations

import json

from rflp_lite.adapters import llm_client


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(
            {"choices": [{"message": {"content": "OK"}}]}
        ).encode()


def test_chat_completion_uses_openai_compatible_endpoint(monkeypatch):
    captured = {}

    def fake_urlopen(call, timeout):
        captured["url"] = call.full_url
        captured["headers"] = dict(call.header_items())
        captured["timeout"] = timeout
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
