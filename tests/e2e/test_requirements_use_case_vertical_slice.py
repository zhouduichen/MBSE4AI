from pathlib import Path

from fastapi.testclient import TestClient

from rflp_lite.interface.web.app import create_app


def test_document_to_requirements_behavior_and_traceability(tmp_path: Path):
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "mission"}).status_code == 200
    source = Path(__file__).parent.parent / "fixtures" / "requirements_use_case_acceptance.txt"

    uploaded = client.post(
        "/projects/mission/documents",
        files={"file": (source.name, source.read_bytes(), "text/plain")},
    )
    assert uploaded.status_code == 200
    document_id = uploaded.json()["document"]["document_id"]

    draft_response = client.post(
        "/projects/mission/requirements-use-case/draft",
        json={"document_ids": [document_id]},
    )
    assert draft_response.status_code == 200
    draft = draft_response.json()["draft"]
    assert len(draft["requirements"]) >= 3
    assert draft["use_cases"]
    assert draft["scenarios"]
    assert draft["system_context"]["attributes"]["platform_type"] == "generic_system"
    assert any(item["kind"] == "stakeholder" for item in draft["entities"])
    assert all(
        item["source_refs"] or item["confidence"] < 1
        for item in draft["requirements"]
    )

    applied = client.post(
        "/projects/mission/requirements-use-case/apply",
        json={"draft_id": draft["draft_id"]},
    )
    assert applied.status_code == 200
    assert applied.json()["apply"]["created_entity_count"] >= 6
    model_after_apply = client.get("/projects/mission/model").json()
    system = next(item for item in model_after_apply["entities"] if item["kind"] == "system")
    assert system["payload"]["attributes"]["platform_type"] == "generic_system"
    assert any(item["kind"] == "stakeholder" for item in model_after_apply["entities"])
    assert any(
        item["payload"].get("inferred_constraints")
        for item in model_after_apply["entities"]
        if item["kind"] == "requirement"
    )

    model = model_after_apply
    candidates = [item for item in model["entities"] if item["kind"] == "requirement"]
    assert len(candidates) >= 3
    accepted = client.post(
        f"/projects/mission/entities/{candidates[0]['id']}/accept",
        json={"expected_revision": model["revision"]},
    )
    assert accepted.status_code == 200
    edited = client.post(
        f"/projects/mission/entities/{candidates[1]['id']}/edit",
        json={
            "expected_revision": accepted.json()["revision"]["sequence"],
            "statement": "系统应记录每次任务的时间、位置和告警状态",
        },
    )
    assert edited.status_code == 200

    behavior = client.get("/projects/mission/behavior")
    assert behavior.status_code == 200
    assert behavior.json()["behavior"]["use_cases"]

    traceability = client.get("/projects/mission/traceability")
    assert traceability.status_code == 200
    assert traceability.json()["traceability"]["rows"]


def test_text_intake_persists_bounded_concern_attributes(tmp_path: Path):
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "profile"}).status_code == 200

    response = client.post(
        "/projects/profile/requirements-use-case/draft",
        json={
            "text": "校园无人配送机器人由操作员使用，维护人员负责维护，系统应故障安全并支持持续运行"
        },
    )
    assert response.status_code == 200
    draft = response.json()["draft"]
    assert draft["system_context"]["attributes"]["platform_type"] == "robot"
    assert {item["name"] for item in draft["entities"]} >= {
        "操作员",
        "维护人员",
        "安全性",
        "可靠性",
        "可维护性",
    }
    assert all(item["confidence"] < 0.5 for item in draft["entities"])

    applied = client.post(
        "/projects/profile/requirements-use-case/apply",
        json={"draft_id": draft["draft_id"]},
    )
    assert applied.status_code == 200
    model = client.get("/projects/profile/model").json()
    system = next(item for item in model["entities"] if item["kind"] == "system")
    assert system["payload"]["attributes"]["platform_type"] == "robot"
    assert any(item["kind"] == "concern" for item in model["entities"])
