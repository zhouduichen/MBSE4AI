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
