import pytest

from rflp_lite.runtime.factory import (
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_MAX_OUTPUT_TOKENS,
    RuntimeFactory,
)


def test_runtime_factory_selects_provider_aware_profile() -> None:
    selection = RuntimeFactory().select(
        {
            "id": "local-ollama",
            "provider": "ollama",
            "kind": "local",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "llama3.2",
            "enabled": True,
        }
    )

    assert selection.configured is True
    assert selection.provider_id == "ollama"
    assert selection.model_id == "llama3.2"


def test_runtime_factory_rejects_disabled_active_profile() -> None:
    with pytest.raises(ValueError, match="disabled"):
        RuntimeFactory().select(
            {
                "id": "disabled",
                "provider": "openai-compatible",
                "model": "gpt-test",
                "enabled": False,
            }
        )


def test_runtime_factory_gives_configured_models_a_full_generation_budget(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_runtime(config):
        captured.update(config)
        return object()

    monkeypatch.setattr(
        "rflp_lite.runtime.factory.openai_compatible_runtime",
        fake_runtime,
    )

    selection = RuntimeFactory().select(
        {
            "id": "remote-model",
            "provider": "openai-compatible",
            "kind": "remote",
            "base_url": "https://example.invalid/v1",
            "model": "engineering-model",
            "enabled": True,
        }
    )

    assert selection.context_window == DEFAULT_CONTEXT_WINDOW == 8192
    assert selection.max_output_tokens == DEFAULT_MAX_OUTPUT_TOKENS == 4096
    assert captured["context_window"] == DEFAULT_CONTEXT_WINDOW
    assert captured["local_context_tokens"] == DEFAULT_CONTEXT_WINDOW
    assert captured["max_output_tokens"] == DEFAULT_MAX_OUTPUT_TOKENS
    assert captured["local_max_tokens"] == DEFAULT_MAX_OUTPUT_TOKENS


def test_runtime_factory_preserves_explicit_generation_budgets(monkeypatch) -> None:
    monkeypatch.setattr(
        "rflp_lite.runtime.factory.openai_compatible_runtime",
        lambda config: object(),
    )

    selection = RuntimeFactory().select(
        {
            "id": "remote-model",
            "provider": "openai-compatible",
            "base_url": "https://example.invalid/v1",
            "model": "engineering-model",
            "context_window": 16384,
            "max_output_tokens": 6144,
        }
    )

    assert selection.context_window == 16384
    assert selection.max_output_tokens == 6144


def test_runtime_factory_exposes_same_configured_model_to_controller():
    selection = RuntimeFactory().select({
        "id": "remote-model",
        "provider": "openai-compatible",
        "kind": "remote",
        "base_url": "https://example.invalid/v1",
        "model": "engineering-model",
        "enabled": True,
    })

    assert selection.controller_model is selection.runtime.model


def test_runtime_factory_offline_selection_has_no_controller_model():
    selection = RuntimeFactory().select(None)

    assert selection.controller_model is None
