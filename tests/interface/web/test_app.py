from pathlib import Path

from fastapi.testclient import TestClient

from rflp_lite.interface.web.app import create_app


def test_app_serves_resource_pages_and_local_assets(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "workspaces"))
    response = client.get("/ui/projects")
    assert response.status_code == 200
    assert "Projects" in response.text
    assert "MBSE Model" in response.text
    css = client.get("/static/app.css")
    assert css.status_code == 200
    assert "--acc" in css.text
    htmx = client.get("/static/vendor/htmx.min.js")
    assert htmx.status_code == 200
