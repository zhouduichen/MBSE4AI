from pathlib import Path

from fastapi.testclient import TestClient

from rflp_lite.application.llm_profiles import LLMProfileService
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


def test_generate_request_profile_overrides_active_profile_without_activation(tmp_path: Path):
    app = create_app(tmp_path / "workspaces")
    app.state.container.v2._runtime_override = VerticalRuleRuntime()
    config_dir = tmp_path / "config"
    app.state.container.v2.settings.profiles.config_dir = config_dir
    app.state.container.v2.settings.profiles.path = config_dir / "llm-profiles.json"
    profiles = LLMProfileService(config_dir)
    profiles.save({
        "id": "active-profile",
        "label": "活动配置",
        "kind": "local",
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "test-local-model",
    })
    profiles.save({
        "id": "remote-profile",
        "label": "远程配置",
        "kind": "remote",
        "provider": "ollama",
        "base_url": "http://remote.example.invalid:11434/v1",
        "model": "qwen3.5:9b-q8_0",
    })
    client = TestClient(app)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    response = client.post(
        "/projects/p1/analysis",
        json={
            "mode": "generate",
            "profile_id": "remote-profile",
            "requirement_text": "系统应支持人工接管",
        },
    )

    assert response.status_code == 200
    run = response.json()["run"]
    assert run["model_profile"] == "remote-profile"
    assert run["provider_id"] == "ollama"
    assert profiles.snapshot()["active_id"] == "active-profile"


def test_generate_response_binds_run_to_revision_bound_deliverable(tmp_path: Path):
    client = _client(tmp_path)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    response = client.post(
        "/projects/p1/analysis",
        json={"mode": "generate", "requirement_text": "系统应支持人工接管"},
    )

    assert response.status_code == 200
    run = response.json()["run"]
    deliverable = run["deliverable"]
    package = client.get("/projects/p1/deliverables").json()["deliverable"]

    assert deliverable["format"] == "ai4mbse.engineering-deliverable.v1"
    assert deliverable["revision"] == run["revision"] == package["revision"]
    assert deliverable["snapshot_hash"] == package["snapshot_hash"]
    assert deliverable["json_url"] == "/projects/p1/deliverables"
    assert deliverable["download_url"] == "/projects/p1/deliverables/download"
    assert deliverable["manifest"] == package["manifest"]
    assert "artifacts" not in deliverable


def test_generate_constraints_returns_technical_requirement_in_traceability_api(tmp_path: Path):
    client = _client(tmp_path)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    response = client.post(
        "/projects/p1/analysis",
        json={"mode": "generate", "requirement_text": "系统功耗不超过 50 W"},
    )

    assert response.status_code == 200
    run = response.json()["run"]
    technical = next(
        item for item in client.get("/projects/p1/model").json()["entities"]
        if item["kind"] == "requirement" and item["payload"].get("level") == "technical"
    )
    trace = client.get("/projects/p1/traceability")

    assert run["traceability"]["end_to_end_complete_count"] >= 2
    assert trace.status_code == 200
    assert any(
        row["requirement_id"] == technical["id"]
        and row["status"] == "PASS"
        and row["physical_blocks"]
        for row in trace.json()["rows"]
    )


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


def test_entity_impact_endpoint_returns_revision_bound_rflp_vv_plan(tmp_path: Path):
    client = _client(tmp_path)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    generated = client.post(
        "/projects/p1/analysis",
        json={"mode": "generate", "requirement_text": "系统应支持人工接管"},
    ).json()["run"]
    model = client.get("/projects/p1/model").json()
    requirement = next(
        item for item in model["entities"] if item["kind"] == "requirement"
    )

    response = client.get(f"/projects/p1/entities/{requirement['id']}/impact")

    assert response.status_code == 200
    payload = response.json()
    impact = payload["impact"]
    assert impact["revision"] == generated["revision"]
    assert requirement["id"] in impact["trigger_entity_ids"]
    assert {"functional", "logical", "physical"} <= set(impact["impacted_stages"])
    assert impact["verification_case_ids"]
    assert impact["validation_case_ids"]
    assert impact["impact_paths"]
    assert payload["controller"]["next_action"]


def test_entity_edit_response_includes_impact_and_controller_for_next_iteration(tmp_path: Path):
    client = _client(tmp_path)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    generated = client.post(
        "/projects/p1/analysis",
        json={"mode": "generate", "requirement_text": "系统应支持人工接管"},
    ).json()["run"]
    requirement = next(
        item for item in client.get("/projects/p1/model").json()["entities"]
        if item["kind"] == "requirement"
    )

    response = client.post(
        f"/projects/p1/entities/{requirement['id']}/edit",
        json={
            "expected_revision": generated["revision"],
            "statement": "系统应支持人工接管并记录接管原因",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["impact"]["revision"] == payload["revision"]["sequence"]
    assert requirement["id"] in payload["impact"]["trigger_entity_ids"]
    assert payload["controller"]["next_action"]


def test_vv_execution_endpoint_records_result_and_exposes_failure_feedback(tmp_path: Path):
    client = _client(tmp_path)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    generated = client.post(
        "/projects/p1/analysis",
        json={"mode": "generate", "requirement_text": "系统应支持人工接管"},
    ).json()["run"]
    model = client.get("/projects/p1/model").json()
    verification = next(
        item for item in model["entities"] if item["kind"] == "verification_case"
    )

    response = client.post(
        f"/projects/p1/vv/{verification['id']}/execute",
        json={
            "outcome": "failed",
            "claim": "接管响应超时",
            "excerpt": "测试日志：响应时间 4.2 s，超过通过准则。",
            "locator": "test.log:42",
            "expected_revision": generated["revision"],
        },
    )

    assert response.status_code == 200
    execution = response.json()["execution"]
    assert execution["outcome"] == "failed"
    assert execution["evidence_id"]
    assert execution["methodology"]["metrics"]["vv_execution_failure_count"] == 1
    assert any(
        item["code"] == "verification_execution_failed"
        for item in client.get("/projects/p1/issues").json()["issues"]
    )


def test_engineering_tool_endpoint_lists_and_executes_registered_model_check(tmp_path: Path):
    client = _client(tmp_path)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    generated = client.post(
        "/projects/p1/analysis",
        json={"mode": "generate", "requirement_text": "系统应支持人工接管"},
    ).json()["run"]
    tools = client.get("/projects/p1/tools")
    assert tools.status_code == 200
    assert any(item["tool_id"] == "model.constraint_check" for item in tools.json()["tools"])
    model = client.get("/projects/p1/model").json()
    verification = next(
        item for item in model["entities"] if item["kind"] == "verification_case"
    )

    response = client.post(
        f"/projects/p1/vv/{verification['id']}/tools/model.constraint_check/execute",
        json={"expected_revision": generated["revision"]},
    )

    assert response.status_code == 200
    execution = response.json()["tool_execution"]
    assert execution["tool_id"] == "model.constraint_check"
    assert execution["outcome"] == "inconclusive"
    assert execution["metadata"]["measurement"] is False


def test_controller_iteration_endpoint_returns_waiting_decision(tmp_path: Path):
    client = _client(tmp_path)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    generated = client.post(
        "/projects/p1/analysis",
        json={"mode": "generate", "requirement_text": "系统应支持人工接管"},
    ).json()["run"]
    model = client.get("/projects/p1/model").json()
    requirement_id = next(item["id"] for item in model["entities"] if item["kind"] == "requirement")
    physical_id = next(item["id"] for item in model["entities"] if item["kind"] == "physical_block")
    edited = client.post(
        f"/projects/p1/entities/{requirement_id}/edit",
        json={
            "expected_revision": generated["revision"],
            "payload": {"constraints": {"max_power_w": 50}},
        },
    )
    edited_physical = client.post(
        f"/projects/p1/entities/{physical_id}/edit",
        json={
            "expected_revision": edited.json()["revision"]["sequence"],
            "payload": {"power_w": 80},
        },
    )
    revision = edited_physical.json()["revision"]["sequence"]

    response = client.post(
        "/projects/p1/controller/iterate",
        json={"max_iterations": 3, "expected_revision": revision},
    )

    assert response.status_code == 200
    payload = response.json()["controller"]
    assert payload["execution_status"] == "awaiting_decision"
    assert payload["revision"] == revision


def test_controller_iteration_endpoint_rejects_stale_revision(tmp_path: Path):
    client = _client(tmp_path)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    response = client.post(
        "/projects/p1/controller/iterate",
        json={"max_iterations": 3, "expected_revision": 9},
    )

    assert response.status_code == 409


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
    model_after = client.get("/projects/p1/model").json()
    alternatives = [
        item for item in model_after["entities"]
        if item["kind"] == "physical_block"
        and item["payload"].get("candidate_variant") == "alternative"
    ]
    assert alternatives
    assert alternatives[0]["payload"]["architecture_decision"]["option_id"] == option["id"]


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
    assert "验证计划完整" in page.text
    assert "确认计划完整" in page.text
    assert "工程检查" in page.text
    assert "物理方案状态" in page.text
    assert "验证与确认闭环" in page.text
    assert "逻辑架构候选" in page.text
    assert "物理可行性矩阵" in page.text
    assert "建议下一步" in page.text
    assert "自动推进可安全执行动作" in page.text
    assert "/controller/iterate" in page.text
    assert 'runAnalysis("generate", null)' in page.text
