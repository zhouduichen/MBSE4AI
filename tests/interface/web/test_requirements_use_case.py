from pathlib import Path

from fastapi.testclient import TestClient

from rflp_lite.interface.web.app import create_app


def test_requirements_use_case_api_and_behavior_page_form_a_vertical_slice(tmp_path: Path):
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    created = client.post(
        "/projects/p1/requirements-use-case/draft",
        json={"text": "操作员应能在 2 秒内接收告警；系统应支持人工接管"},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "ok"
    draft = body["draft"]
    assert draft["status"] == "degraded"
    assert len(draft["requirements"]) == 2
    assert draft["use_cases"]
    assert draft["scenarios"]
    inferred = [
        constraint
        for requirement in draft["requirements"]
        for constraint in requirement["constraints"]
        if constraint["source"] == "derived"
    ]
    assert any(item["field"] == "human_override" for item in inferred)
    assert all(item["assumption"] and item["confidence"] < 0.5 for item in inferred)

    applied = client.post(
        "/projects/p1/requirements-use-case/apply",
        json={"draft_id": draft["draft_id"]},
    )
    assert applied.status_code == 200
    assert applied.json()["apply"]["created_entity_count"] >= 4

    repeated = client.post(
        "/projects/p1/requirements-use-case/apply",
        json={"draft_id": draft["draft_id"]},
    )
    assert repeated.status_code == 200
    assert repeated.json()["apply"]["idempotent"] is True

    behavior_api = client.get("/projects/p1/behavior")
    assert behavior_api.status_code == 200
    sequence_diagrams = behavior_api.json()["sequence_diagrams"]
    assert sequence_diagrams
    assert sequence_diagrams[0]["format"] == "mermaid"
    assert "sequenceDiagram" in sequence_diagrams[0]["mermaid"]
    assert sequence_diagrams[0]["editable_entity_ids"]

    behavior = client.get("/ui/projects/p1/behavior")
    assert behavior.status_code == 200
    assert "Use Case Framework" in behavior.text
    assert "Operational Scenario Framework" in behavior.text
    assert "Sequence Diagram Framework" in behavior.text
    assert "操作员" in behavior.text

    intake = client.get("/ui/projects/p1/requirements-use-case")
    assert intake.status_code == 200
    assert "需求与用例提取" in intake.text
    assert draft["draft_id"] in intake.text
    assert "需人工确认" in intake.text


def test_requirements_use_case_drafts_are_listed_with_remote_safe_metadata(tmp_path: Path):
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    created = client.post(
        "/projects/p1/requirements-use-case/draft",
        json={"text": "系统应支持人工接管"},
    )
    assert created.status_code == 200

    listed = client.get("/projects/p1/requirements-use-case/drafts")
    assert listed.status_code == 200
    assert len(listed.json()["drafts"]) == 1
    assert "api_key" not in listed.text
