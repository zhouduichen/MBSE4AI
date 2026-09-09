from pathlib import Path

from fastapi.testclient import TestClient

from rflp_lite.interface.web.app import create_app


def test_analysis_page_shows_full_harness_workflow(tmp_path: Path) -> None:
    app = create_app(tmp_path / "workspaces")
    app.state.container.v2.settings.profiles.config_dir = tmp_path / "config"
    app.state.container.v2.settings.profiles.path = tmp_path / "config" / "llm-profiles.json"
    client = TestClient(app)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    response = client.get("/ui/projects/p1/analysis")
    assert response.status_code == 200
    for label in (
        "Operational",
        "Functional",
        "Logical/Physical",
        "Assurance",
        "Closure",
        "Current Revision",
        "Active Model",
        "Run Status",
        "Global Gate",
        "Evidence",
        "Attempt",
        "Patch",
        "Validation",
        "Gate Issues",
        "Repair",
        "Closure Summary",
        "Offline Rule Mode",
    ):
        assert label in response.text


def test_analysis_api_supports_pipeline_and_force_run(tmp_path: Path) -> None:
    app = create_app(tmp_path / "workspaces")
    app.state.container.v2.settings.profiles.config_dir = tmp_path / "config"
    app.state.container.v2.settings.profiles.path = tmp_path / "config" / "llm-profiles.json"
    client = TestClient(app)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    initial = client.get("/projects/p1/analysis")
    assert initial.status_code == 200
    payload = initial.json()
    assert payload["current_revision"] == 0
    assert payload["runtime"]["mode"] == "Offline Rule Mode"
    assert [item["name"] for item in payload["phases"]] == [
        "Operational",
        "Functional",
        "Logical/Physical",
        "Assurance",
        "Closure",
    ]

    response = client.post(
        "/projects/p1/analysis",
        json={"mode": "pipeline", "force_run": True},
    )
    assert response.status_code == 200
    run = response.json()["run"]
    assert run["mode"] == "pipeline"
    assert run["force_run"] is True
    assert [item["phase"] for item in run["phase_results"]] == [
        "operational",
        "functional",
        "logical_physical",
        "assurance",
        "closure",
    ]
    assert "gate_results" in run

    refreshed = client.get("/projects/p1/analysis").json()
    assert refreshed["latest_run"]["run_id"] == run["run_id"]
    assert refreshed["global_gate"]["gate_id"] == "Global-Gate"


def test_single_phase_analysis_keeps_legacy_shape(tmp_path: Path) -> None:
    app = create_app(tmp_path / "workspaces")
    app.state.container.v2.settings.profiles.config_dir = tmp_path / "config"
    app.state.container.v2.settings.profiles.path = tmp_path / "config" / "llm-profiles.json"
    client = TestClient(app)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    response = client.post(
        "/projects/p1/analysis",
        json={"phase": "operational"},
    )
    assert response.status_code == 200
    run = response.json()["run"]
    assert run["phase"] == "operational"
    assert "completed_tasks" in run
    assert "diagnostics" in run


def test_computed_gate_issue_can_start_targeted_repair(tmp_path: Path) -> None:
    app = create_app(tmp_path / "workspaces")
    app.state.container.v2.settings.profiles.config_dir = tmp_path / "config"
    app.state.container.v2.settings.profiles.path = tmp_path / "config" / "llm-profiles.json"
    client = TestClient(app)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    issues = client.get("/projects/p1/analysis").json()["gate_issues"]
    issue = next(item for item in issues if item["code"] == "missing_verification")
    response = client.post("/projects/p1/repair", json={"issue_id": issue["id"]})

    assert response.status_code == 200
    assert response.json()["repair"]["root_cause"] == "verification"
    assert "re_gate" in response.json()["repair"]
