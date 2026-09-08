from pathlib import Path

from fastapi.testclient import TestClient

from rflp_lite.interface.web.app import create_app


def test_resource_api_project_model_and_cas_patch(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    assert client.get("/projects/p1/model").json()["revision"] == 0
    response = client.patch("/projects/p1/entities/missing", json={"expected_revision": 0, "field_patch": {"name": "x"}})
    assert response.status_code == 422


def test_resource_api_can_delete_a_project_and_returns_404_afterward(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    response = client.delete("/projects/p1")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "project_id": "p1"}
    missing = client.delete("/projects/p1")
    assert missing.status_code == 404
    assert missing.json()["error"] == "NotFoundError"
