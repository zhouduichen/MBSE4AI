from __future__ import annotations

from pathlib import Path

from rflp_lite.application.llm_profiles import LLMProfileService, normalize_profile


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


def test_ollama_remote_profile_can_be_tested_without_api_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("rflp_lite.application.llm_profiles._keyring", lambda: None)
    service = LLMProfileService(tmp_path / "config")
    payload = {
        "id": "ollama-remote",
        "kind": "remote",
        "provider": "ollama",
        "base_url": "http://10.0.0.8:11434/v1",
        "model": "qwen3.5:9b",
    }

    result = service.test(payload, tester=lambda config: {"provider": config["provider"]})

    assert result == {"provider": "ollama"}


def test_llm_profile_preserves_local_generation_controls(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("rflp_lite.application.llm_profiles._keyring", lambda: None)
    service = LLMProfileService(tmp_path / "config")

    saved = service.save({
        "id": "ollama-controls",
        "kind": "local",
        "provider": "ollama",
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "qwen3.5:9b-q8_0",
        "local_context_tokens": 8192,
        "local_max_tokens": 2048,
        "temperature": 0,
        "seed": 42,
        "structured_output_mode": "json_schema",
    })

    assert saved["context_window"] == 8192
    assert saved["max_output_tokens"] == 2048
    assert saved["local_context_tokens"] == 8192
    assert saved["local_max_tokens"] == 2048
    assert saved["temperature"] == 0.0
    assert saved["seed"] == 42
    assert saved["structured_output_mode"] == "json_schema"


def test_ssh_forward_profile_distinguishes_remote_model_from_local_endpoint(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("rflp_lite.application.llm_profiles._keyring", lambda: None)
    service = LLMProfileService(tmp_path / "config")

    saved = service.save({
        "id": "jiayuinter-vllm",
        "kind": "local",
        "model_location": "remote",
        "provider": "openai-compatible",
        "base_url": "http://127.0.0.1:18000/v1",
        "model": "qwen3.5-controller",
    })

    assert saved["model_location"] == "remote"
    assert service.active_config()["model_location"] == "remote"


def test_llm_profile_preserves_remote_reasoning_controls(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("rflp_lite.application.llm_profiles._keyring", lambda: None)
    profile = normalize_profile({
        **_payload(),
        "id": "qwen-remote",
        "reasoning_effort": "none",
        "think": False,
    })

    assert profile["reasoning_effort"] == "none"
    assert profile["think"] is False


def test_llm_profile_preserves_chat_template_controls() -> None:
    profile = normalize_profile({
        **_payload(),
        "chat_template_kwargs": {"enable_thinking": False},
    })

    assert profile["chat_template_kwargs"] == {"enable_thinking": False}


def test_remote_qwen35_structured_profile_disables_thinking_by_default() -> None:
    profile = normalize_profile({
        **_payload(),
        "id": "qwen-remote",
        "kind": "local",
        "model_location": "remote",
        "model": "qwen3.5-controller",
    })

    assert profile["chat_template_kwargs"] == {"enable_thinking": False}


def test_remote_qwen35_explicit_thinking_control_wins() -> None:
    profile = normalize_profile({
        **_payload(),
        "id": "qwen-remote",
        "kind": "local",
        "model_location": "remote",
        "model": "qwen3.5-controller",
        "chat_template_kwargs": {"enable_thinking": True},
    })

    assert profile["chat_template_kwargs"] == {"enable_thinking": True}


def test_remote_profile_allows_long_running_generation_timeout() -> None:
    profile = normalize_profile({
        **_payload(),
        "id": "jiayuinter-vllm",
        "base_url": "http://127.0.0.1:18000/v1",
        "timeout_seconds": 900,
    })

    assert profile["timeout_seconds"] == 900


def test_remote_profile_defaults_to_mixed_r_backbone_and_allows_compatibility_mode() -> None:
    remote = normalize_profile({
        **_payload(),
        "id": "jiayuinter-vllm",
        "kind": "local",
        "model_location": "remote",
        "base_url": "http://127.0.0.1:18000/v1",
        "model": "qwen3.5-controller",
    })
    local = normalize_profile({
        "id": "local-model",
        "kind": "local",
        "model_location": "local",
        "base_url": "http://127.0.0.1:1234/v1",
        "model": "local-model",
    })
    opted_in = normalize_profile({
        **remote,
        "vertical_feedback": True,
    })
    compatibility = normalize_profile({
        **remote,
        "r_backbone_single_kind": True,
    })

    assert remote["vertical_feedback"] is False
    assert remote["vertical_batch_size"] == 2
    assert remote["vertical_batch_output_tokens"] == 3072
    assert local["vertical_feedback"] is True
    assert local["vertical_batch_size"] == 2
    assert local["vertical_batch_output_tokens"] == 3072
    assert opted_in["vertical_feedback"] is True
    assert remote["vertical_completion_bridge"] is False
    assert local["vertical_completion_bridge"] is True
    assert remote["automatic_operational_completion"] is True
    assert remote["vertical_vv_case_splitting"] is True
    assert remote["r_backbone_single_kind"] is False
    assert compatibility["r_backbone_single_kind"] is True


def test_llm_profile_can_disable_vertical_completion_bridge() -> None:
    profile = normalize_profile({
        **_payload(),
        "id": "strict-remote",
        "model_location": "remote",
        "vertical_completion_bridge": False,
    })

    assert profile["vertical_completion_bridge"] is False


def test_llm_profile_can_disable_remote_completion_loops_and_vv_case_splitting() -> None:
    profile = normalize_profile({
        **_payload(),
        "id": "first-pass-remote",
        "model_location": "remote",
        "automatic_operational_completion": False,
        "vertical_vv_case_splitting": False,
    })

    assert profile["automatic_operational_completion"] is False
    assert profile["vertical_vv_case_splitting"] is False


def test_llm_profile_defaults_remote_parallelism_lower_than_local() -> None:
    remote = normalize_profile({
        **_payload(),
        "id": "remote-parallel",
        "model_location": "remote",
    })
    local = normalize_profile({
        **_payload(),
        "id": "local-parallel",
        "kind": "local",
        "model_location": "local",
        "base_url": "http://127.0.0.1:1234/v1",
        "model": "local-model",
    })
    explicit = normalize_profile({
        **remote,
        "max_parallel_requests": 1,
    })

    assert remote["max_parallel_requests"] == 2
    assert local["max_parallel_requests"] == 4
    assert explicit["max_parallel_requests"] == 1
