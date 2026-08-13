from pathlib import Path

from fastapi.testclient import TestClient

from rflp_lite.interface.web.app import create_app


def _client(tmp_path: Path) -> TestClient:
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/workspaces", data={"name": "medical"}, follow_redirects=False).status_code == 303
    response = client.post("/w/medical/requirements/analyze", data={"text": "设计一款城市医疗用途的飞行汽车"}, follow_redirects=False)
    assert response.status_code == 303
    return client


def test_discovery_page_and_local_degraded_run(tmp_path: Path):
    client = _client(tmp_path)
    response = client.get("/w/medical/requirements/discovery")
    assert response.status_code == 200
    assert "智能补全" in response.text
    run = client.post("/api/v1/workspaces/medical/discovery/draft", json={"pack_id": "urban-medical-aam-v1"})
    assert run.status_code == 200
    payload = run.json()
    assert payload["discovery"]["intake"]
    assert any(item["code"] in {"generative_model_unavailable", "generative_model_failed"} for item in payload["discovery"]["diagnostics"])


def test_review_endpoint_requires_current_revision(tmp_path: Path):
    client = _client(tmp_path)
    client.post("/api/v1/workspaces/medical/discovery/draft", json={"pack_id": "urban-medical-aam-v1"})
    response = client.post("/api/v1/workspaces/medical/discovery/review", json={"candidate_id": "candidate-1", "decision": "accepted", "expected_revision": 0, "pack_id": "urban-medical-aam-v1"})
    assert response.status_code == 422
