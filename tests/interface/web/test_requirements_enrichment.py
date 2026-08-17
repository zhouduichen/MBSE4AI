import time
from pathlib import Path

from fastapi.testclient import TestClient

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import AdapterFailure
from rflp_lite.interface.web.app import create_app
from rflp_lite.ports.generative_model import GenerationResponse


class BlockModel:
    def __init__(self):
        self.calls = []

    def complete_json(self, request):
        block_id = request.user_payload["block_id"]
        self.calls.append(block_id)
        if block_id == "requirements":
            raise AdapterFailure("requirements block failed")
        payload = {
            "items": (
                [{"id": "operator", "name": "运营人员", "category": "operator"}]
                if block_id == "stakeholders"
                else []
            ),
            "diagnostics": [],
        }
        return GenerationResponse(
            request.lens_id,
            payload,
            canonical_hash(request.user_payload),
            canonical_hash(payload),
            False,
        )


def _wait(client: TestClient):
    for _ in range(160):
        state = client.get("/api/v1/workspaces/demo/requirements").json()["requirements"]
        job_id = state.get("auto_analysis", {}).get("job_id")
        if job_id:
            job = client.get(f"/api/v1/workspaces/demo/jobs/{job_id}").json()["job"]
            if job["status"] in {"completed", "degraded", "failed"}:
                return job
        time.sleep(0.02)
    raise AssertionError("enrichment job did not finish")


def test_submit_returns_baseline_and_retry_keeps_successful_blocks(tmp_path: Path, monkeypatch):
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/workspaces", data={"name": "demo"}, follow_redirects=False).status_code == 303
    model = BlockModel()
    monkeypatch.setattr(client.app.state.facade, "_project_analysis_model", lambda: model)

    submitted = client.post(
        "/w/demo/requirements/analyze",
        data={"text": "系统应支持备份。"},
        follow_redirects=False,
    )
    assert submitted.status_code == 303
    baseline = client.get("/api/v1/workspaces/demo/requirements").json()["requirements"]
    assert baseline["claims"]
    assert all(item["status"] == "accepted" for item in baseline["claims"])

    first = _wait(client)
    assert first["status"] == "degraded"
    assert first["blocks"]["stakeholders"] == "succeeded"
    first_success_calls = model.calls.count("stakeholders")

    retry = client.post(
        f"/api/v1/workspaces/demo/requirements/enrichment/{first['id']}/retry"
    )
    assert retry.status_code == 200
    second = _wait(client)
    assert second["blocks"]["stakeholders"] == "succeeded"
    assert model.calls.count("stakeholders") == first_success_calls
