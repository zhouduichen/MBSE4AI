from pathlib import Path

from fastapi.testclient import TestClient

from rflp_lite.interface.web.app import create_app


def test_settings_page_and_connection_test_do_not_expose_credentials(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    client = TestClient(create_app(tmp_path / "workspaces", container=None))
    client.app.state.container.v2.settings.profiles.config_dir = config_dir
    client.app.state.container.v2.settings.profiles.path = config_dir / "llm-profiles.json"

    save = client.post(
        "/model-profiles",
        json={
            "id": "local-test",
            "label": "Local Test",
            "kind": "remote",
            "base_url": "http://127.0.0.1:1/v1",
            "model": "fake-model",
            "api_key": "do-not-return-this-secret",
        },
    )
    assert save.status_code == 200
    second = client.post(
        "/model-profiles",
        json={
            "id": "local-second",
            "label": "Local Second",
            "kind": "local",
            "base_url": "http://127.0.0.1:2/v1",
            "model": "second-model",
        },
    )
    assert second.status_code == 200

    page = client.get("/ui/settings")
    assert page.status_code == 200
    assert "连接测试" in page.text
    assert 'id="profile-save-form"' in page.text
    assert 'id="profile-timeout"' in page.text
    assert 'id="profile-provider"' in page.text
    assert 'id="profile-preset"' in page.text
    assert "delete-profile" in page.text
    assert "激活" in page.text
    assert "do-not-return-this-secret" not in page.text
    assert "实际运行时" in page.text

    test = client.post("/model-profiles/test", json={"profile_id": "local-test"})
    assert test.status_code == 200
    result = test.json()
    assert result["profile_id"] == "local-test"
    assert result["model_id"] == "fake-model"
    assert "connected" in result
    assert "do-not-return-this-secret" not in test.text

    profiles = client.get("/model-profiles").json()
    assert profiles["active_id"] == "local-test"
    assert profiles["profiles"][0]["api_key_configured"] is True
    activate = client.post("/model-profiles/local-second/activate")
    assert activate.status_code == 200
    assert client.get("/model-profiles").json()["active_id"] == "local-second"


def test_model_profile_presets_and_delete_are_exposed_without_secrets(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "workspaces", container=None))
    config_dir = tmp_path / "config"
    client.app.state.container.v2.settings.profiles.config_dir = config_dir
    client.app.state.container.v2.settings.profiles.path = config_dir / "llm-profiles.json"

    presets = client.get("/model-profiles/presets")
    assert presets.status_code == 200
    assert presets.json()["presets"]["ollama"]["provider"] == "ollama"
    assert presets.json()["presets"]["openai"]["provider"] == "openai-compatible"

    assert client.post(
        "/model-profiles",
        json={
            "id": "to-delete",
            "label": "待删除",
            "kind": "local",
            "provider": "ollama",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "llama3.2",
        },
    ).status_code == 200
    deleted = client.delete("/model-profiles/to-delete")
    assert deleted.status_code == 200
    assert deleted.json()["active_id"] is None
    assert client.get("/model-profiles").json()["profiles"] == []
