import pytest

from rflp_lite.adapters.openai_compatible_model import OpenAICompatibleModel
from rflp_lite.domain.errors import AdapterFailure
from rflp_lite.ports.generative_model import (
    GenerationRequest,
    SIMPLIFIED_CHINESE_OUTPUT_INSTRUCTION,
)


def request() -> GenerationRequest:
    return GenerationRequest(
        lens_id="stakeholders",
        system_prompt="只返回 JSON",
        user_payload={"mission": "城市医疗运输"},
        response_schema={
            "type": "object",
            "required": ["items"],
            "properties": {"items": {"type": "array"}},
        },
        max_tokens=1200,
    )


def long_request() -> GenerationRequest:
    result = request()
    return GenerationRequest(
        lens_id=result.lens_id,
        system_prompt=result.system_prompt,
        user_payload=result.user_payload,
        response_schema={
            "type": "object",
            "required": ["items"],
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 2000},
                }
            },
        },
        max_tokens=result.max_tokens,
    )


def test_adapter_parses_json_and_records_hashes():
    calls = []

    def complete(config, messages, *, max_tokens=None):
        calls.append((config, messages, max_tokens))
        return '{"items":[]}'

    result = OpenAICompatibleModel({"model": "local"}, complete=complete).complete_json(request())
    assert result.payload == {"items": []}
    assert result.input_hash and result.output_hash
    assert result.model_id == "local"
    assert result.provider_id == "openai-compatible"
    assert result.duration_ms >= 0
    assert result.status == "completed"
    assert result.repaired is False
    assert calls[0][2] == 1200


def test_adapter_adds_simplified_chinese_instruction_to_initial_prompt():
    calls = []

    def complete(_config, messages, *, max_tokens=None):
        calls.append(messages)
        return '{"items":[]}'

    OpenAICompatibleModel({"model": "local"}, complete=complete).complete_json(request())

    assert SIMPLIFIED_CHINESE_OUTPUT_INSTRUCTION in calls[0][0]["content"]
    assert "只返回 JSON" in calls[0][0]["content"]


def test_adapter_adds_simplified_chinese_instruction_to_repair_prompt():
    calls = []
    answers = iter(("not-json", '{"items":[]}'))

    def complete(_config, messages, *, max_tokens=None):
        calls.append(messages)
        return next(answers)

    OpenAICompatibleModel({"model": "local"}, complete=complete).complete_json(request())

    assert SIMPLIFIED_CHINESE_OUTPUT_INSTRUCTION in calls[1][0]["content"]
    assert "重新生成完整的 JSON 分析结果" in calls[1][0]["content"]


def test_adapter_repairs_invalid_json_once():
    answers = iter(("not-json", '{"items":[]}'))
    model = OpenAICompatibleModel(
        {"model": "local"}, complete=lambda *_args, **_kwargs: next(answers)
    )
    result = model.complete_json(request())
    assert result.payload == {"items": []}
    assert result.repaired is True


def test_adapter_repairs_provider_length_stop_with_full_budget():
    class TruncatedText(str):
        done_reason = "length"

    answers = iter((TruncatedText('{"items": ['), '{"items":[]}'))
    calls = []

    def complete(_config, _messages, *, max_tokens=None):
        calls.append(max_tokens)
        return next(answers)

    result = OpenAICompatibleModel(
        {"kind": "local", "model": "qwen", "local_max_tokens": 3000},
        complete=complete,
    ).complete_json(request())

    assert result.repaired is True
    assert calls == [1200, 2400]


def test_adapter_passes_request_schema_to_local_completion():
    captured = {}

    def complete(config, messages, *, max_tokens=None):
        captured["config"] = config
        return '{"items":[]}'

    model = OpenAICompatibleModel(
        {"kind": "local", "model": "qwen3.5:4b"}, complete=complete
    )
    model.complete_json(request())

    assert captured["config"]["json_schema"] == request().response_schema


def test_ollama_transport_schema_removes_only_grammar_incompatible_length_limit():
    captured = {}

    def complete(config, messages, *, max_tokens=None):
        captured["config"] = config
        captured["messages"] = messages
        return '{"items":[]}'

    model = OpenAICompatibleModel(
        {
            "kind": "local",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen3.5:4b",
        },
        complete=complete,
    )
    model.complete_json(long_request())

    sent_schema = captured["config"]["json_schema"]
    assert sent_schema["properties"]["items"]["items"] == {"type": "string"}
    assert "response_schema" not in __import__("json").loads(
        captured["messages"][1]["content"]
    )


def test_adapter_parses_fenced_json_from_reasoning_fallback():
    model = OpenAICompatibleModel(
        {"model": "local"},
        complete=lambda *_args, **_kwargs: "分析完成：```json\n{\"items\": []}\n```",
    )

    result = model.complete_json(request())

    assert result.payload == {"items": []}


def test_adapter_fails_after_one_invalid_json_repair():
    model = OpenAICompatibleModel({"model": "local"}, complete=lambda *_args, **_kwargs: "not-json")
    with pytest.raises(AdapterFailure, match="JSON"):
        model.complete_json(request())


@pytest.mark.parametrize(
    "first_response",
    (
        "",
        '{"items": [',
        '{"items": "not-a-list"}',
    ),
)
def test_adapter_rejects_empty_truncated_and_schema_invalid_repair(first_response):
    calls = []

    def complete(_config, _messages, *, max_tokens=None):
        calls.append(max_tokens)
        return first_response

    model = OpenAICompatibleModel(
        {"kind": "local", "model": "qwen", "local_max_tokens": 900},
        complete=complete,
    )
    with pytest.raises(
        AdapterFailure, match="LLM response is not valid JSON after one repair"
    ):
        model.complete_json(request())

    assert calls == [900, 900]


def test_adapter_validates_repaired_json_against_schema():
    answers = iter(('{"items": "not-a-list"}', '{"items":[]}'))
    model = OpenAICompatibleModel(
        {"kind": "local", "model": "qwen"},
        complete=lambda *_args, **_kwargs: next(answers),
    )

    result = model.complete_json(request())

    assert result.payload == {"items": []}
    assert result.repaired is True


def test_adapter_wraps_repair_provider_failure_stably():
    calls = 0

    def complete(_config, _messages, *, max_tokens=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return "truncated"
        raise RuntimeError("provider disconnected")

    model = OpenAICompatibleModel(
        {"kind": "local", "model": "qwen"}, complete=complete
    )
    with pytest.raises(
        AdapterFailure, match="LLM response is not valid JSON after one repair"
    ):
        model.complete_json(request())

    assert calls == 2


def test_adapter_uses_smaller_request_budget_when_local_cap_is_larger():
    calls = []

    def complete(_config, _messages, *, max_tokens=None):
        calls.append(max_tokens)
        return '{"items":[]}'

    model = OpenAICompatibleModel(
        {"kind": "local", "model": "qwen", "local_max_tokens": 2400},
        complete=complete,
    )
    model.complete_json(request())

    assert calls == [1200]


def test_adapter_repair_keeps_full_block_budget_and_contains_only_block_envelope():
    calls = []
    answers = iter(("truncated", '{"items":[]}'))

    def complete(_config, messages, *, max_tokens=None):
        calls.append((messages, max_tokens))
        return next(answers)

    model = OpenAICompatibleModel(
        {"kind": "local", "model": "qwen", "local_max_tokens": 2400},
        complete=complete,
    )
    model.complete_json(request())

    repair_messages, repair_budget = calls[1]
    assert repair_budget == 1200
    assert "重新生成完整的 JSON 分析结果" in repair_messages[0]["content"]
    assert "invalid_response" in repair_messages[1]["content"]
    assert "response_schema" in repair_messages[1]["content"]


def test_local_adapter_caps_large_output_requests():
    calls = []

    def complete(config, messages, *, max_tokens=None):
        calls.append(max_tokens)
        return '{"items":[]}'

    model = OpenAICompatibleModel(
        {"kind": "local", "model": "qwen", "local_max_tokens": 600},
        complete=complete,
    )
    model.complete_json(request())

    assert calls == [600]
