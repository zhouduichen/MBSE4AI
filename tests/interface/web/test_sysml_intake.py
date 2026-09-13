from __future__ import annotations

from fastapi.testclient import TestClient

from tests.interface.web.test_requirements_workbench import _client_with_fixture
from rflp_lite.interface.web.app import create_app


def test_sysml_upload_imports_model_and_reports_counts(tmp_path):
    client = TestClient(create_app(tmp_path))
    assert client.post("/projects", json={"id": "source"}).status_code == 200
    assert client.post(
        "/projects/source/requirements",
        json={"text": "系统应支持模型导入"},
    ).status_code == 200
    exported = client.post("/projects/source/export", json={"format": "sysml"})
    assert exported.status_code == 200
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    response = client.post(
        "/projects/p1/sysml/import/upload",
        files={"file": ("model.sysml", exported.text, "text/plain")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["entity_count"] == 1
    assert payload["relation_count"] == 0


def test_sysml_upload_conflict_does_not_mutate_revision(tmp_path):
    client, _ = _client_with_fixture(tmp_path)
    exported = client.post("/projects/p1/export", json={"format": "sysml"})
    before = client.get("/projects/p1/model").json()["revision"]

    response = client.post(
        "/projects/p1/sysml/import/upload",
        files={"file": ("model.sysml", exported.text, "text/plain")},
    )

    assert response.status_code == 422
    assert client.get("/projects/p1/model").json()["revision"] == before


def test_imported_model_can_be_edited_and_exported(tmp_path):
    client, _ = _client_with_fixture(tmp_path)
    exported = client.post("/projects/p1/export", json={"format": "sysml"})
    assert exported.status_code == 200
    assert client.post("/projects", json={"id": "p2"}).status_code == 200

    imported = client.post(
        "/projects/p2/sysml/import/upload",
        files={"file": ("existing.sysml", exported.text, "text/plain")},
    )

    assert imported.status_code == 200
    model = client.get("/projects/p2/model").json()
    entity = next(item for item in model["entities"] if item["kind"] == "function")
    edited = client.patch(
        f"/projects/p2/entities/{entity['id']}",
        json={
            "expected_revision": model["revision"],
            "field_patch": {"name": "人工编辑功能"},
        },
    )

    assert edited.status_code == 200
    bundle = client.get("/projects/p2/deliverables/download")
    assert bundle.status_code == 200
    assert bundle.headers["content-type"].startswith("application/zip")
