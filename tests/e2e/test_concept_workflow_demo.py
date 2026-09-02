from __future__ import annotations

from fastapi.testclient import TestClient

from rflp_lite.interface.web.app import create_app


TEXT = (
    "设计一型中程侦察无人机，最大起飞重量不超过 650 kg，任务载荷至少 150 kg，"
    "翼展 ≤ 16 m，巡航速度 >= 240 km/h，机翼面积等于 24 m2，机身长度等于 9 m，"
    "截面模量等于 0.032 m3，许用应力等于 205000000 Pa，重心位置等于 2.7 m。"
)


def test_concept_workflow_demo_api_and_latest_page(tmp_path) -> None:
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/workspaces", data={"name": "demo"}, follow_redirects=False).status_code == 303

    response = client.post(
        "/api/v1/workspaces/demo/concept-workflow",
        json={"text": TEXT, "seed": 42, "demo_mode": True},
    )
    assert response.status_code == 200, response.text
    workflow = response.json()["workflow"]
    assert workflow["status"] == "completed"
    assert [item["key"] for item in workflow["steps"]] == [
        "requirements_completed",
        "mbse_completed",
        "envelope_completed",
        "retrieval_completed",
        "generation_completed",
        "evaluation_completed",
        "optimization_completed",
    ]
    assert len(workflow["generation"]["initial_candidate_ids"]) == 5
    assert len(workflow["candidates"]) >= 7
    assert workflow["optimization"]["iteration_records"]
    assert workflow["optimization"]["pareto_svg"].startswith("<svg")
    assert workflow["envelope"]["source_requirement_ids"]

    latest = client.get("/api/v1/workspaces/demo/concept-workflow")
    assert latest.status_code == 200
    assert latest.json()["workflow"]["result_hash"] == workflow["result_hash"]
    page = client.get("/w/demo/concept-design")
    assert page.status_code == 200
    assert "development-only" in page.text
    assert "Top 3" in page.text
    assert "Pareto" in page.text
    assert "三维 CAD" in page.text
    assert workflow["recommendation"]["candidate_id"] in page.text
    assert client.get("/api/v1/workspaces/demo/requirements").status_code == 200

    selected = client.post(
        f"/api/v1/workspaces/demo/concept-workflow/{workflow['run_id']}/baseline",
        json={"candidate_id": workflow["recommendation"]["candidate_id"], "rationale": "Pareto 前沿"},
    )
    assert selected.status_code == 200
    assert selected.json()["baseline"]["decision"] == "provisional_selected"
    assert client.get(f"/w/demo/concept-design?run_id={workflow['run_id']}").status_code == 200


def test_concept_workflow_accepts_one_sentence_without_pack_or_history(tmp_path) -> None:
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/workspaces", data={"name": "generic"}, follow_redirects=False).status_code == 303

    response = client.post(
        "/api/v1/workspaces/generic/concept-workflow",
        json={"text": "我想做一个更安全的设备。", "demo_mode": False},
    )

    assert response.status_code == 200, response.text
    workflow = response.json()["workflow"]
    assert workflow["status"] == "provisional"
    assert workflow["domain_pack"] == {}
    assert workflow["mbse"]
    assert workflow["status"] != "failed"
    page = client.get("/w/generic/concept-design")
    assert page.status_code == 200
    assert "临时概念草案" in page.text or "LLM-first" in page.text
