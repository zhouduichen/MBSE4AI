from pathlib import Path

from fastapi.testclient import TestClient

from rflp_lite.interface.web.app import create_app


def _client(tmp_path: Path) -> TestClient:
    client = TestClient(create_app(tmp_path / "workspaces"))
    client.post("/workspaces", data={"name": "demo"})
    facade = client.app.state.facade
    facade._project_analysis_model = lambda: None
    facade.analyze_requirements("demo", "requirements.txt", "管理员必须恢复历史版本。".encode(), merge=False)
    facade.accept_traceable_requirements("demo")
    facade.generate_requirements_mbse("demo")
    return client


def test_mbse_view_catalog_and_render_endpoint_preserve_project_scope(tmp_path: Path):
    client = _client(tmp_path)

    listed = client.get("/api/v1/workspaces/demo/requirements/mbse/views")
    assert listed.status_code == 200
    ids = {item["id"] for item in listed.json()["views"]}
    assert {"rflp", "operational_scenario", "allocation_matrix"} <= ids

    rendered = client.get(
        "/api/v1/workspaces/demo/requirements/mbse/views/rflp",
        params={"engine": "fallback", "format": "svg"},
    )
    assert rendered.status_code == 200
    payload = rendered.json()["view"]
    assert payload["engine_id"] == "fallback"
    assert "mbse-professional-svg" in payload["content"]

    foreign = client.get(
        "/api/v1/workspaces/foreign/requirements/mbse/views"
    )
    assert foreign.status_code == 404
