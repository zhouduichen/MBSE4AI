import pytest

from rflp_lite.runtime.factory import RuntimeFactory


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
