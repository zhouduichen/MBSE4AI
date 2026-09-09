from __future__ import annotations

from pathlib import Path

from rflp_lite.application.llm_profiles import LLMProfileService


def _payload() -> dict[str, object]:
    return {
        "id": "deepseek-main",
        "label": "DeepSeek 主模型",
        "kind": "remote",
        "protocol": "openai-chat",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-pro",
        "api_key": "secret-key",
    }


def test_llm_profile_keeps_key_out_of_config_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("rflp_lite.application.llm_profiles._keyring", lambda: None)
    service = LLMProfileService(tmp_path / "config")

    saved = service.save(_payload())
    assert saved["id"] == "deepseek-main"
    assert saved["provider"] == "openai-compatible"
    assert saved["api_key_configured"] is True
    assert "secret-key" not in service.path.read_text(encoding="utf-8")
    assert service.active_config()["api_key"] == "secret-key"

    listed = service.snapshot()
    assert listed["active_id"] == "deepseek-main"
    assert listed["profiles"][0]["credential_storage"] == "session"


def test_llm_profile_preserves_key_when_edit_form_is_blank(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("rflp_lite.application.llm_profiles._keyring", lambda: None)
    service = LLMProfileService(tmp_path / "config")
    service.save(_payload())

    edited = {**_payload(), "label": "修改后的模型", "api_key": ""}
    service.save(edited)

    assert service.active_config()["api_key"] == "secret-key"
    assert service.snapshot()["profiles"][0]["label"] == "修改后的模型"


def test_llm_profile_infers_ollama_provider_from_legacy_url(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("rflp_lite.application.llm_profiles._keyring", lambda: None)
    service = LLMProfileService(tmp_path / "config")

    saved = service.save({
        "id": "ollama-legacy",
        "label": "Ollama",
        "kind": "local",
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "llama3.2",
    })

    assert saved["provider"] == "ollama"
    assert service.active_config()["provider"] == "ollama"


def test_llm_profile_presets_include_both_providers(tmp_path: Path) -> None:
    presets = LLMProfileService(tmp_path / "config").presets()

    assert presets["openai"]["provider"] == "openai-compatible"
    assert presets["ollama"]["provider"] == "ollama"


def test_deleting_active_profile_repairs_active_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("rflp_lite.application.llm_profiles._keyring", lambda: None)
    service = LLMProfileService(tmp_path / "config")
    service.save({**_payload(), "id": "first"})
    service.save({**_payload(), "id": "second", "api_key": ""})
    service.activate("first")

    result = service.delete("first")

    assert result == {"profile_id": "first", "active_id": "second"}
    assert service.snapshot()["active_id"] == "second"
