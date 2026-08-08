from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rflp_lite.interface.web.app import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "workspaces"))


def _workbench(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})
    response = client.post(
        "/w/demo/requirements/analyze",
        data={"text": "管理员必须恢复历史版本。"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_api_v1_reads_and_executes_local_scenario(client: TestClient) -> None:
    _workbench(client)

    created = client.post(
        "/api/v1/workspaces/demo/scenarios",
        json={
            "title": "恢复版本",
            "description": "验证恢复流程",
            "steps": ["选择版本", "确认恢复"],
            "expected_outcomes": ["内容恢复"],
        },
    )
    assert created.status_code == 200
    scenario_id = created.json()["scenario"]["id"]

    listed = client.get("/api/v1/workspaces/demo/scenarios")
    assert listed.status_code == 200
    assert listed.json()["scenarios"][0]["id"] == scenario_id

    executed = client.post(f"/api/v1/workspaces/demo/scenarios/{scenario_id}/execute")
    assert executed.status_code == 200
    body = executed.json()
    assert body["status"] == "ok"
    execution = body["execution"]
    assert execution["status"] == "completed"
    assert execution["verification"] == "declarative-only"

    job_id = execution["job"]["id"]
    job = client.get(f"/api/v1/workspaces/demo/jobs/{job_id}")
    assert job.status_code == 200
    assert job.json()["job"]["status"] == "succeeded"


def test_api_v1_profile_and_error_contract(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})

    profile = client.get("/api/v1/workspaces/demo/profile")
    assert profile.status_code == 200
    updated = client.put(
        "/api/v1/workspaces/demo/profile",
        json={
            "name": "local-editor",
            "solver": "heuristic",
            "seed": 8,
            "candidate_limit": 2,
            "timeout_seconds": 10,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["profile"]["name"] == "local-editor"

    missing = client.get("/api/v1/workspaces/missing/profile")
    assert missing.status_code == 404
    assert missing.json()["status"] == "failed"


def test_api_v1_exposes_local_plugin_registry(client: TestClient) -> None:
    plugins = client.get("/api/v1/plugins")

    assert plugins.status_code == 200
    assert plugins.json()["plugins"][0]["name"] == "scenario-trace"

    missing = client.post("/api/v1/plugins/missing", json={})
    assert missing.status_code == 422
    assert missing.json()["status"] == "failed"
