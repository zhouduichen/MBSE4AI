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
    behavior_payload = behavior_api.json()
    model_payload = client.get("/projects/p1/model").json()
    requirement_ids = {
        item["id"]
        for item in model_payload["entities"]
        if item["kind"] == "requirement"
    }
    behavior_relation_sources = {
        item["source"]
        for item in behavior_payload["relations"]
        if item["source"] in requirement_ids
    }
    assert behavior_relation_sources == requirement_ids
    assert requirement_ids <= {
        requirement_id
        for item in behavior_payload["use_cases"]
        for requirement_id in item["requirement_ids"]
    }
    sequence_diagrams = behavior_payload["sequence_diagrams"]
    assert sequence_diagrams
    assert sequence_diagrams[0]["format"] == "mermaid"
    assert "sequenceDiagram" in sequence_diagrams[0]["mermaid"]
    assert sequence_diagrams[0]["editable_entity_ids"]
    assert requirement_ids <= set(sequence_diagrams[0]["requirement_ids"])
    activity_diagrams = behavior_payload["activity_diagrams"]
    assert activity_diagrams
    assert activity_diagrams[0]["format"] == "mermaid"
    assert "flowchart TD" in activity_diagrams[0]["mermaid"]
    assert requirement_ids <= set(activity_diagrams[0]["requirement_ids"])

    use_case = behavior_payload["use_cases"][0]
    use_case_payload = dict(use_case["payload"])
    use_case_payload["goal"] = "人工确认后的任务目标"
    edited_use_case = client.post(
        f"/projects/p1/entities/{use_case['id']}/edit",
        json={
            "expected_revision": model_payload["revision"],
            "name": "人工确认用例",
            "payload": use_case_payload,
        },
    )
    assert edited_use_case.status_code == 200
    after_use_case = client.get("/projects/p1/behavior").json()
    updated_use_case = next(item for item in after_use_case["use_cases"] if item["id"] == use_case["id"])
    assert updated_use_case["name"] == "人工确认用例"
    assert updated_use_case["goal"] == "人工确认后的任务目标"

    current_model = client.get("/projects/p1/model").json()
    activity_id = sequence_diagrams[0]["editable_entity_ids"][1]
    activity = next(item for item in current_model["entities"] if item["id"] == activity_id)
    activity_payload = dict(activity["payload"])
    activity_payload["action"] = "人工修改后的活动"
    edited_activity = client.post(
        f"/projects/p1/entities/{activity_id}/edit",
        json={
            "expected_revision": current_model["revision"],
            "payload": activity_payload,
        },
    )
    assert edited_activity.status_code == 200
    after_activity = client.get("/projects/p1/behavior").json()
    assert any(
        message["action"] == "人工修改后的活动"
        for diagram in after_activity["sequence_diagrams"]
        for message in diagram["messages"]
    )

    behavior = client.get("/ui/projects/p1/behavior")
    assert behavior.status_code == 200
    assert "Use Case Framework" in behavior.text
    assert "Operational Scenario Framework" in behavior.text
    assert "Sequence Diagram Framework" in behavior.text
    assert "Activity Diagram Framework" in behavior.text
    assert "操作员" in behavior.text
    assert "来源需求" in behavior.text
    assert "直接编辑" in behavior.text
    assert 'data-behavior-edit-form=' in behavior.text
    assert next(iter(requirement_ids)) in behavior.text
    use_case_id = behavior_payload["use_cases"][0]["id"]
    assert f"/ui/projects/p1/model#entity-{use_case_id}" in behavior.text
    model_page = client.get("/ui/projects/p1/model")
    assert model_page.status_code == 200
    assert f'id="entity-{use_case_id}"' in model_page.text

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
