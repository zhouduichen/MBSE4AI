from __future__ import annotations

import io
import zipfile

from fastapi.testclient import TestClient

from tests.interface.web.test_requirements_workbench import _client_with_fixture
from rflp_lite.interface.web.app import create_app
from rflp_lite.runtime.rule_based import VerticalRuleRuntime


def test_deliverables_api_returns_single_revision_package(tmp_path):
    client, _ = _client_with_fixture(tmp_path)

    response = client.get("/projects/p1/deliverables")

    assert response.status_code == 200
    package = response.json()["deliverable"]
    assert package["format"] == "ai4mbse.engineering-deliverable.v1"
    assert package["revision"] == package["artifacts"]["model"]["content"]["revision"]
    assert package["snapshot_hash"] == package["artifacts"]["traceability"]["content"]["snapshot_hash"]
    assert package["artifacts"]["evidence"]["content"]["project_id"] == "p1"


def test_deliverables_download_is_zip(tmp_path):
    client, _ = _client_with_fixture(tmp_path)

    response = client.get("/projects/p1/deliverables/download")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")
    assert response.headers["content-disposition"] == (
        'attachment; filename="p1-engineering-deliverables.zip"'
    )
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert "architecture-report.md" in archive.namelist()
        assert "vv-plan.md" in archive.namelist()
        assert "evidence.json" in archive.namelist()
        assert "behavior.json" in archive.namelist()
        assert archive.read("rflp.svg").startswith(b"<svg")


def test_downloaded_sysml_can_be_imported_and_edited(tmp_path):
    client, _ = _client_with_fixture(tmp_path)
    download = client.get("/projects/p1/deliverables/download")
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        sysml = archive.read("model.sysml")

    assert client.post("/projects", json={"id": "p2"}).status_code == 200
    imported = client.post("/projects/p2/sysml/import", content=sysml)
    assert imported.status_code == 200

    model = client.get("/projects/p2/model").json()
    entity = next(item for item in model["entities"] if item["kind"] == "function")
    edited = client.patch(
        f"/projects/p2/entities/{entity['id']}",
        json={
            "expected_revision": model["revision"],
            "field_patch": {"payload": {"review_note": "继续编辑"}},
        },
    )

    assert edited.status_code == 200
    updated = client.get("/projects/p2/model").json()
    updated_entity = next(item for item in updated["entities"] if item["id"] == entity["id"])
    assert updated_entity["payload"]["review_note"] == "继续编辑"


def test_deliverables_expose_generated_technical_requirement(tmp_path):
    app = create_app(tmp_path / "workspaces")
    app.state.container.v2._runtime_override = VerticalRuleRuntime()
    client = TestClient(app)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    generated = client.post(
        "/projects/p1/analysis",
        json={"mode": "generate", "requirement_text": "系统功耗不超过 50 W"},
    )
    assert generated.status_code == 200

    package = client.get("/projects/p1/deliverables").json()["deliverable"]
    model_entities = package["artifacts"]["model"]["content"]["entities"]
    technical = next(
        item for item in model_entities
        if item["kind"] == "requirement" and item["payload"].get("level") == "technical"
    )
    trace_rows = package["artifacts"]["traceability"]["content"]["rows"]
    vv_rows = package["artifacts"]["vv_plan"]["content"]["rows"]

    assert technical["payload"]["constraints"] == {"max_power_w": 50.0}
    assert any(row["requirement_id"] == technical["id"] and row["status"] == "PASS" for row in trace_rows)
    assert {row["requirement_id"] for row in vv_rows if row["requirement_id"] == technical["id"]} == {technical["id"]}
