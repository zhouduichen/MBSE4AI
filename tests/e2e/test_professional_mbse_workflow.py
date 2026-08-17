from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.interface.web.app import create_app
from rflp_lite.ports.generative_model import GenerationResponse


class FixtureModel:
    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, request):
        self.calls += 1
        workspace = str(request.user_payload["project_scope"]["workspace"])
        payload = {
            "system": {
                "name": f"{workspace}任务系统",
                "domain": "通用",
                "mission": "安全完成任务",
            },
            "stakeholders": [
                {
                    "id": "operator",
                    "name": f"{workspace}操作员",
                    "category": "operator",
                    "goals": ["完成任务"],
                }
            ],
            "concerns": [
                {"id": "c-task", "name": "任务完成", "stakeholder_id": "operator"}
            ],
            "needs": [
                {
                    "id": "n-task",
                    "name": "任务支持",
                    "statement": "操作员需要可靠完成任务",
                    "stakeholder_id": "operator",
                    "concern_id": "c-task",
                }
            ],
            "requirements": [
                {
                    "id": "r-dispatch",
                    "statement": "系统应支持任务调度",
                    "subject": "系统",
                    "predicate": "应",
                    "source_type": "inferred",
                },
                {
                    "id": "r-record",
                    "statement": "系统应记录任务结果",
                    "subject": "系统",
                    "predicate": "应",
                    "source_type": "inferred",
                },
            ],
            "scenarios": [
                {
                    "id": "s-normal",
                    "title": "正常任务",
                    "scenario_type": "normal",
                    "actors": [f"{workspace}操作员"],
                    "steps": ["创建任务", "执行任务"],
                    "expected_outcomes": ["任务完成"],
                    "requirement_ids": ["r-dispatch", "r-record"],
                },
                {
                    "id": "s-failure",
                    "title": "任务失败",
                    "scenario_type": "failure",
                    "actors": [f"{workspace}操作员"],
                    "steps": ["检测异常", "记录故障"],
                    "expected_outcomes": ["进入安全处置"],
                    "requirement_ids": ["r-record"],
                },
            ],
            "architecture": {
                "functions": [
                    {
                        "id": "f-dispatch",
                        "name": "任务调度",
                        "requirement_ids": ["r-dispatch"],
                    },
                    {
                        "id": "f-record",
                        "name": "结果记录",
                        "requirement_ids": ["r-record"],
                    },
                ],
                "logical_components": [
                    {
                        "id": "l-control",
                        "name": "任务控制逻辑",
                        "requirement_ids": ["r-dispatch", "r-record"],
                    }
                ],
                "physical_components": [
                    {
                        "id": "p-controller",
                        "name": "任务控制器",
                        "requirement_ids": ["r-dispatch", "r-record"],
                    }
                ],
                "interfaces": [
                    {
                        "id": "i-operator",
                        "name": "操作接口",
                        "source_id": "operator",
                        "target_id": "l-control",
                    }
                ],
                "relations": [],
            },
            "open_questions": [],
        }
        return GenerationResponse(
            request.lens_id,
            payload,
            canonical_hash(request.user_payload),
            canonical_hash(payload),
            False,
        )


def _wait_for_job(client: TestClient, workspace: str) -> None:
    for _ in range(160):
        state = client.get(f"/api/v1/workspaces/{workspace}/requirements").json()["requirements"]
        job_id = state.get("auto_analysis", {}).get("job_id")
        if job_id:
            job = client.get(f"/api/v1/workspaces/{workspace}/jobs/{job_id}").json()["job"]
            if job["status"] in {"completed", "degraded", "failed"}:
                return
        time.sleep(0.02)
    raise AssertionError("enrichment job did not finish")


def test_project_mbse_workflow_is_isolated_editable_and_view_complete(
    tmp_path: Path, monkeypatch
) -> None:
    client = TestClient(create_app(tmp_path / "workspaces"))
    for name in ("alpha", "beta"):
        assert (
            client.post(
                "/workspaces", data={"name": name}, follow_redirects=False
            ).status_code
            == 303
        )

    model = FixtureModel()
    monkeypatch.setattr(client.app.state.facade, "_project_analysis_model", lambda: model)
    for name in ("alpha", "beta"):
        response = client.post(
            f"/w/{name}/requirements/analyze",
            data={"text": f"设计{name}任务系统"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        _wait_for_job(client, name)

    alpha = client.get("/api/v1/workspaces/alpha/requirements").json()["requirements"]
    beta_before = client.get("/api/v1/workspaces/beta/requirements").json()["requirements"]
    assert model.calls == 12
    assert alpha["auto_analysis"]["status"] == "completed"
    assert alpha["stakeholders"] and alpha["scenarios"]
    assert alpha["rflp"] and alpha["mbse"]["semantic_model"]["sections"]["technical_requirements"]

    catalog = client.get("/api/v1/workspaces/alpha/requirements/mbse/views")
    assert catalog.status_code == 200
    view_ids = {item["id"] for item in catalog.json()["views"]}
    assert {"rflp", "operational_scenario", "allocation_matrix", "traceability_matrix"} <= view_ids
    for view_id in ("rflp", "operational_scenario", "allocation_matrix", "traceability_matrix"):
        rendered = client.get(
            f"/api/v1/workspaces/alpha/requirements/mbse/views/{view_id}",
            params={"engine": "fallback", "format": "svg"},
        )
        assert rendered.status_code == 200
        assert rendered.json()["view"]["engine_id"] == "fallback"
        assert rendered.json()["view"]["content"].startswith("<svg")
    assert model.calls == 12, "rendering views must not trigger another LLM analysis"

    edited_id = alpha["claims"][0]["id"]
    edited = client.post(
        "/w/alpha/requirements/review",
        data={
            "group": "claims",
            "item_id": edited_id,
            "status": "accepted",
            "value": "系统应支持修改后的任务调度",
        },
        follow_redirects=False,
    )
    assert edited.status_code == 303
    alpha_after_edit = client.get("/api/v1/workspaces/alpha/requirements").json()["requirements"]
    assert alpha_after_edit["rflp"] is None
    assert alpha_after_edit["mbse"] is None
    assert any(item["object"] == "系统应支持修改后的任务调度" for item in alpha_after_edit["claims"])

    assert client.post("/w/alpha/requirements/confirm-and-generate", follow_redirects=False).status_code == 303
    assert client.post("/w/alpha/requirements/mbse", follow_redirects=False).status_code == 303
    alpha_regenerated = client.get("/api/v1/workspaces/alpha/requirements").json()["requirements"]
    delete_id = next(item["id"] for item in alpha_regenerated["claims"] if item["id"] != edited_id)
    deleted = client.post(
        "/w/alpha/requirements/delete",
        data={"requirement_id": delete_id},
        follow_redirects=False,
    )
    assert deleted.status_code == 303

    alpha_after_delete = client.get("/api/v1/workspaces/alpha/requirements").json()["requirements"]
    beta_after = client.get("/api/v1/workspaces/beta/requirements").json()["requirements"]
    remaining_ids = {item["id"] for item in alpha_after_delete["claims"]}
    assert edited_id in remaining_ids
    assert delete_id not in remaining_ids
    assert delete_id not in str(alpha_after_delete["mbse"])
    assert beta_after["claims"] == beta_before["claims"]
    assert beta_after["mbse"] == beta_before["mbse"]
    assert model.calls == 12
