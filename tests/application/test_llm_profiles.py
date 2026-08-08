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
