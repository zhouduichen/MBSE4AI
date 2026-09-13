from pathlib import Path

from fastapi.testclient import TestClient

from rflp_lite.interface.web.app import create_app
from rflp_lite.runtime.rule_based import VerticalRuleRuntime


def _client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path / "workspaces")
    app.state.container.v2._runtime_override = VerticalRuleRuntime()
    return TestClient(app)


def test_generate_mode_returns_stage_and_traceability_payload(tmp_path: Path):
    client = _client(tmp_path)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    response = client.post(
        "/projects/p1/analysis",
        json={"mode": "generate", "requirement_text": "系统应支持自主配送并允许人工接管"},
    )

    assert response.status_code == 200
    run = response.json()["run"]
    assert run["mode"] == "generate"
    assert [item["stage"] for item in run["stage_results"]] == [
        "requirements", "functional", "logical", "physical", "verification_validation"
    ]
    assert run["traceability"]["complete_count"] >= 1


def test_sysml_import_api_round_trips_into_fresh_project(tmp_path: Path):
    client = _client(tmp_path)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    assert client.post("/projects", json={"id": "p2"}).status_code == 200
    generated = client.post(
        "/projects/p1/analysis",
        json={"mode": "generate", "requirement_text": "系统应支持人工接管"},
    ).json()["run"]

    exported = client.post("/projects/p1/export", json={"format": "sysml"})
    response = client.post("/projects/p2/sysml/import", content=exported.content)

    assert generated["status"] == "completed"
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["revision"] == 1


def test_analysis_page_exposes_default_generation_action(tmp_path: Path):
    client = _client(tmp_path)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    assert client.post("/projects/p1/requirements", json={"text": "系统应支持人工接管"}).status_code == 200

    page = client.get("/ui/projects/p1/analysis")

    assert page.status_code == 200
    assert "生成完整 MBSE 模型" in page.text
    assert 'runAnalysis("generate", null)' in page.text
