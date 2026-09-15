import json

import pytest

from rflp_lite.adapters.openai_compatible_model import OpenAICompatibleModel
from rflp_lite.adapters.llm_client import _fit_context_window
from rflp_lite.domain.errors import AdapterFailure, StructuredOutputFailure, TransportFailure
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


def test_openai_compatible_model_enables_requirement_batching():
    assert OpenAICompatibleModel({"model": "remote"}).supports_requirement_batching is True


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


def test_adapter_fits_output_to_configured_context_window():
    calls = []

    def complete(_config, _messages, *, max_tokens=None):
        calls.append(max_tokens)
        return '{"items": []}'

    model = OpenAICompatibleModel(
        {
            "provider": "ollama",
            "kind": "local",
            "context_window": 2048,
            "model": "qwen",
        },
        complete=complete,
    )
    model.complete_json(
        GenerationRequest(
            lens_id="stakeholders",
            system_prompt="只返回 JSON",
                user_payload={"mission": "城市医疗运输" * 140},
            response_schema=request().response_schema,
            max_tokens=1200,
        )
    )

    assert 0 < calls[0] < 1200


def test_adapter_rejects_prompt_when_context_window_cannot_fit_output():
    model = OpenAICompatibleModel(
        {
            "provider": "ollama",
            "kind": "local",
            "context_window": 512,
            "model": "qwen",
        },
        complete=lambda *_args, **_kwargs: '{"items": []}',
    )

    with pytest.raises(TransportFailure, match="context window") as error:
        model.complete_json(
            GenerationRequest(
                lens_id="stakeholders",
                system_prompt="只返回 JSON",
                user_payload={"mission": "城市医疗运输" * 300},
                response_schema=request().response_schema,
                max_tokens=1200,
            )
        )

    assert error.value.code == "context_window_exceeded"


def test_context_window_margin_covers_provider_tokenizer_boundary():
    messages = [{"role": "user", "content": "中" * 12220}]

    # The model-independent estimate is exactly at the old 64-token boundary;
    # a provider counting 65 additional wrapper/punctuation tokens would
    # reject the resulting 4096-token request against a 16384-token window.
    assert _fit_context_window(
        {"context_window": 16384}, messages, 4096
    ) == 3904


def test_adapter_preserves_finish_reason_and_usage():
    class CompletedText(str):
        done_reason = "stop"
        usage = {"prompt_tokens": 4, "completion_tokens": 3}

    result = OpenAICompatibleModel(
        {"model": "local"},
        complete=lambda *_args, **_kwargs: CompletedText('{"items": []}'),
    ).complete_json(request())

    assert result.finish_reason == "stop"
    assert result.usage == {"prompt_tokens": 4, "completion_tokens": 3}


def test_adapter_reports_final_finish_reason_and_usage_after_repair():
    class InitialText(str):
        done_reason = "length"
        usage = {"completion_tokens": 1200}

    class RepairedText(str):
        done_reason = "stop"
        usage = {"completion_tokens": 5}

    answers = iter((InitialText('{"items": ['), RepairedText('{"items": []}')))
    result = OpenAICompatibleModel(
        {"kind": "local", "model": "qwen"},
        complete=lambda *_args, **_kwargs: next(answers),
    ).complete_json(request())

    assert result.repaired is True
    assert result.finish_reason == "stop"
    assert result.usage == {"completion_tokens": 5}


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


def test_adapter_passes_request_schema_to_openai_compatible_completion():
    captured = {}

    def complete(config, messages, *, max_tokens=None):
        captured["config"] = config
        return '{"items":[]}'

    model = OpenAICompatibleModel(
        {
            "kind": "local",
            "provider": "openai-compatible",
            "base_url": "http://127.0.0.1:18000/v1",
            "model": "qwen3.5-controller",
        },
        complete=complete,
    )
    model.complete_json(request())

    assert captured["config"]["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "stakeholders",
            "strict": True,
            "schema": request().response_schema,
        },
    }


def test_ollama_receives_task_proposal_schema_as_format():
    captured = {}
    proposal = GenerationRequest(
        lens_id="task",
        system_prompt="只返回 TaskProposal",
        user_payload={},
        response_schema={
            "type": "object",
            "required": ["entities", "relations", "updates", "deprecations", "reason"],
            "properties": {
                "entities": {"type": "array"},
                "relations": {"type": "array"},
                "updates": {"type": "array"},
                "deprecations": {"type": "array"},
                "reason": {"type": "string"},
            },
        },
    )

    def complete(config, _messages, *, max_tokens=None):
        captured["config"] = config
        return '{"entities": [], "relations": [], "updates": [], "deprecations": [], "reason": "无变化"}'

    OpenAICompatibleModel(
        {"kind": "local", "provider": "ollama", "model": "qwen3.5:9b-q8_0"},
        complete=complete,
    ).complete_json(proposal)

    assert captured["config"]["json_schema"]["required"] == proposal.response_schema["required"]


def test_structured_output_mode_none_disables_native_provider_constraint():
    captured = {}

    def complete(config, _messages, *, max_tokens=None):
        captured["config"] = config
        return '{"items": []}'

    OpenAICompatibleModel(
        {
            "kind": "local",
            "provider": "ollama",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen3.5:9b",
            "structured_output_mode": "none",
        },
        complete=complete,
    ).complete_json(request())

    assert "json_schema" not in captured["config"]


def test_openai_compatible_receives_structured_response_format():
    captured = {}
    proposal = request()

    def complete(config, _messages, *, max_tokens=None):
        captured["config"] = config
        return '{"items": []}'

    OpenAICompatibleModel(
        {"model": "remote", "structured_output_mode": "json_schema"},
        complete=complete,
    ).complete_json(proposal)

    assert captured["config"]["response_format"]["type"] == "json_schema"
    assert captured["config"]["response_format"]["json_schema"]["schema"] == proposal.response_schema


def test_openai_json_schema_is_not_repeated_in_prompt():
    captured = {}

    def complete(config, messages, *, max_tokens=None):
        captured["config"] = config
        captured["messages"] = messages
        return '{"items": []}'

    OpenAICompatibleModel(
        {
            "provider": "openai-compatible",
            "model": "remote",
            "structured_output_mode": "json_schema",
        },
        complete=complete,
    ).complete_json(request())

    assert "response_schema" not in json.loads(captured["messages"][1]["content"])
    assert captured["config"]["response_format"]["type"] == "json_schema"


def test_openai_provider_schema_avoids_unsupported_one_of_but_keeps_common_shape():
    captured = {}
    proposal = request()
    proposal.response_schema["oneOf"] = [{"required": ["items"]}]
    proposal.response_schema["x-payload-schemas"] = {"requirement": {"type": "object"}}

    def complete(config, _messages, *, max_tokens=None):
        captured["config"] = config
        return '{"items": []}'

    OpenAICompatibleModel(
        {"provider": "openai-compatible", "model": "remote"},
        complete=complete,
    ).complete_json(proposal)

    provider_schema = captured["config"]["response_format"]["json_schema"]["schema"]
    assert "oneOf" not in provider_schema
    assert "x-payload-schemas" not in provider_schema
    assert provider_schema["required"] == proposal.response_schema["required"]


def test_openai_compatible_honors_json_object_output_mode():
    captured = {}

    def complete(config, _messages, *, max_tokens=None):
        captured["config"] = config
        return '{"items": []}'

    OpenAICompatibleModel(
        {
            "kind": "local",
            "provider": "openai-compatible",
            "base_url": "http://127.0.0.1:18000/v1",
            "model": "qwen3.5-controller",
            "structured_output_mode": "json_object",
        },
        complete=complete,
    ).complete_json(request())

    assert captured["config"]["response_format"] == {"type": "json_object"}


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


def test_ollama_structural_repair_does_not_duplicate_schema_in_prompt():
    calls = []
    answers = iter(("not-json", '{"items":[]}'))

    def complete(config, messages, *, max_tokens=None):
        calls.append((config, messages))
        return next(answers)

    model = OpenAICompatibleModel(
        {
            "kind": "local",
            "provider": "ollama",
            "base_url": "http://100.88.143.10:11434/v1",
            "model": "qwen3.5:9b-q8_0",
        },
        complete=complete,
    )
    model.complete_json(request())

    repair_payload = __import__("json").loads(calls[1][1][1]["content"])
    assert "response_schema" not in repair_payload


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


def test_invalid_structured_output_exposes_raw_response_and_one_retry():
    calls = []

    def complete(_config, _messages, *, max_tokens=None):
        calls.append(max_tokens)
        return "not-json" if len(calls) == 1 else "still-not-json"

    with pytest.raises(StructuredOutputFailure) as error:
        OpenAICompatibleModel({"kind": "local", "model": "qwen"}, complete=complete).complete_json(request())

    assert calls == [1200, 1200]
    assert error.value.stage == "structural"
    assert error.value.code == "json_decode"
    assert error.value.raw_response == "still-not-json"
    assert error.value.initial_raw_response == "not-json"
    assert error.value.retry_count == 1
    assert error.value.schema_hash


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
        {
            "kind": "local",
            "model": "qwen",
            "local_max_tokens": 2400,
            "structured_output_mode": "json_object",
        },
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
