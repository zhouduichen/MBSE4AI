from __future__ import annotations

import io
import zipfile

from tests.interface.web.test_requirements_workbench import _client_with_fixture


def test_deliverables_api_returns_single_revision_package(tmp_path):
    client, _ = _client_with_fixture(tmp_path)

    response = client.get("/projects/p1/deliverables")

    assert response.status_code == 200
    package = response.json()["deliverable"]
    assert package["format"] == "ai4mbse.engineering-deliverable.v1"
    assert package["revision"] == package["artifacts"]["model"]["content"]["revision"]
    assert package["snapshot_hash"] == package["artifacts"]["traceability"]["content"]["snapshot_hash"]


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
