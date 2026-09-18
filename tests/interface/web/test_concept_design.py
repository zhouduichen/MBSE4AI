from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from rflp_lite.interface.web.app import create_app


ROOT = Path("src/rflp_lite/resources/examples/concept-design")


def test_concept_design_api_generates_evaluates_and_applies(tmp_path):
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    envelope = json.loads((ROOT / "fixed-wing-envelope.json").read_text(encoding="utf-8"))

    response = client.post(
        "/projects/p1/concept-design/run",
        json={"envelope": envelope, "optimize": False},
    )
    assert response.status_code == 200
    run = response.json()["run"]
    assert 3 <= len(run["candidates"]) <= 5
    assert len(run["evaluations"]) == len(run["candidates"]) * 3
    assert run["formal_status"] == "development"

    applied = client.post(
        f"/projects/p1/concept-design/{run['id']}/apply",
        json={"candidate_id": run["candidates"][0]["id"]},
    )
    assert applied.status_code == 200
    assert applied.json()["apply"]["entity"]["kind"] == "physical_block"
    assert client.get("/ui/projects/p1/concept-design").status_code == 200
