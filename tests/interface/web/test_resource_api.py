from pathlib import Path

from fastapi.testclient import TestClient

from rflp_lite.interface.web.app import create_app


def test_resource_api_project_model_and_cas_patch(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    assert client.get("/projects/p1/model").json()["revision"] == 0
    response = client.patch("/projects/p1/entities/missing", json={"expected_revision": 0, "field_patch": {"name": "x"}})
    assert response.status_code == 422
