from pathlib import Path

from fastapi.testclient import TestClient

from rflp_lite.interface.web.app import create_app


def test_app_serves_local_assets_and_empty_dashboard(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "workspaces"))
    response = client.get("/")
    assert response.status_code == 200
    assert "RFLP-Lite" in response.text
    assert "尚无工作区" in response.text
    css = client.get("/static/app.css")
    assert css.status_code == 200
    assert "--color-accent" in css.text
    htmx = client.get("/static/vendor/htmx.min.js")
    assert htmx.status_code == 200
