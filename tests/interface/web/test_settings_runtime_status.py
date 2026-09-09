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

    page = client.get("/ui/settings")
    assert page.status_code == 200
    assert "连接测试" in page.text
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
