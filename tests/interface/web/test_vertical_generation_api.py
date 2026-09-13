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
    assert run["traceability"]["rflp_complete_count"] >= 1
    assert run["traceability"]["verification_complete_count"] >= 1
    assert run["traceability"]["validation_complete_count"] >= 1
    assert run["traceability"]["end_to_end_complete_count"] >= 1
    assert "methodology" in run
    assert "physical_measurement_required" in {
        item["code"] for item in run["methodology"]["findings"]
    }
    assert run["controller"]["status"] == "needs_action"
    assert run["controller"]["next_action"]["kind"] == "collect_evidence"


def test_controller_plan_and_execution_endpoint_expose_next_action(tmp_path: Path):
    client = _client(tmp_path)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    generated = client.post(
        "/projects/p1/analysis",
        json={"mode": "generate", "requirement_text": "系统应支持人工接管"},
    ).json()["run"]

    plan_response = client.get("/projects/p1/controller")
    assert plan_response.status_code == 200
    plan = plan_response.json()["controller"]
    assert plan["next_action"]["id"] == generated["controller"]["next_action"]["id"]

    execution = client.post(
        "/projects/p1/controller/execute",
        json={"action_id": plan["next_action"]["id"], "expected_revision": generated["revision"]},
    )
    assert execution.status_code == 200
    assert execution.json()["controller"]["execution_status"] == "awaiting_evidence"


def test_controller_trade_study_decision_runs_only_affected_downstream_stages(tmp_path: Path):
    client = _client(tmp_path)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    generated = client.post(
        "/projects/p1/analysis",
        json={"mode": "generate", "requirement_text": "系统应支持人工接管"},
    ).json()["run"]
    model = client.get("/projects/p1/model").json()
    requirement_id = next(item["id"] for item in model["entities"] if item["kind"] == "requirement")
    physical_id = next(item["id"] for item in model["entities"] if item["kind"] == "physical_block")

    edited_requirement = client.post(
        f"/projects/p1/entities/{requirement_id}/edit",
        json={
            "expected_revision": generated["revision"],
            "payload": {"constraints": {"max_power_w": 50}},
        },
    )
    revision = edited_requirement.json()["revision"]["sequence"]
    edited_physical = client.post(
        f"/projects/p1/entities/{physical_id}/edit",
        json={"expected_revision": revision, "payload": {"power_w": 80}},
    )
    revision = edited_physical.json()["revision"]["sequence"]
    plan = client.get("/projects/p1/controller").json()["controller"]
    action = next(item for item in plan["actions"] if item["kind"] == "trade_study")
    option = next(item for item in action["options"] if item["task_id"] == "allocation_tradeoff")

    proposed = client.post(
        "/projects/p1/controller/execute",
        json={"action_id": action["id"], "expected_revision": revision},
    )
    assert proposed.json()["controller"]["execution_status"] == "awaiting_decision"
    decided = client.post(
        "/projects/p1/controller/execute",
        json={
            "action_id": action["id"],
            "option_id": option["id"],
            "expected_revision": revision,
        },
    )

    assert decided.status_code == 200
    payload = decided.json()["controller"]
    assert payload["execution_status"] == "completed"
    assert payload["decision"]["option_id"] == option["id"]
    assert payload["reanalysis"]["selected_stages"] == [
        "physical", "verification_validation"
    ]
    assert payload["reanalysis"]["controller_decision"]["option_id"] == option["id"]


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


def test_document_upload_can_seed_the_complete_generation_path(tmp_path: Path):
    client = _client(tmp_path)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    uploaded = client.post(
        "/projects/p1/documents",
        files={"file": ("requirements.txt", "系统应支持人工接管\n", "text/plain")},
    )

    assert uploaded.status_code == 200
    generated = client.post("/projects/p1/analysis", json={"mode": "generate"})

    assert generated.status_code == 200
    run = generated.json()["run"]
    assert run["status"] in {"completed", "completed_with_warnings"}
    assert [item["stage"] for item in run["stage_results"]] == [
        "requirements", "functional", "logical", "physical", "verification_validation"
    ]
    requirement = next(
        item for item in client.get("/projects/p1/model").json()["entities"]
        if item["kind"] == "requirement"
    )
    assert requirement["source_ids"]


def test_analysis_page_exposes_default_generation_action(tmp_path: Path):
    client = _client(tmp_path)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    assert client.post("/projects/p1/requirements", json={"text": "系统应支持人工接管"}).status_code == 200
    assert client.post(
        "/projects/p1/analysis",
        json={"mode": "generate", "requirement_text": "系统应支持人工接管"},
    ).status_code == 200

    page = client.get("/ui/projects/p1/analysis")

    assert page.status_code == 200
    assert "生成完整 MBSE 模型" in page.text
    assert "端到端闭环" in page.text
    assert "Verification" in page.text
    assert "Validation" in page.text
    assert "Methodology Findings" in page.text
    assert "Physical feasibility" in page.text
    assert "V&amp;V Coverage" in page.text
    assert "Next Tasks" in page.text
    assert 'runAnalysis("generate", null)' in page.text
