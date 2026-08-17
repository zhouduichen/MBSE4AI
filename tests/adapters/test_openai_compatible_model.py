import pytest

from rflp_lite.adapters.openai_compatible_model import OpenAICompatibleModel
from rflp_lite.domain.errors import AdapterFailure
from rflp_lite.ports.generative_model import GenerationRequest


def request() -> GenerationRequest:
    return GenerationRequest(
        lens_id="stakeholders",
        system_prompt="只返回 JSON",
        user_payload={"mission": "城市医疗运输"},
        response_schema={"type": "object"},
        max_tokens=1200,
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
    assert result.duration_ms >= 0
    assert calls[0][2] == 1200


def test_adapter_repairs_invalid_json_once():
    answers = iter(("not-json", '{"items":[]}'))
    model = OpenAICompatibleModel(
        {"model": "local"}, complete=lambda *_args, **_kwargs: next(answers)
    )
    result = model.complete_json(request())
    assert result.payload == {"items": []}
    assert result.repaired is True


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
