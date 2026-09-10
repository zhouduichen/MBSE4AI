from tests.interface.web.test_requirements_workbench import _client_with_fixture


def test_review_actions_create_revision_audit_and_protect_locked_entity(tmp_path):
    client, requirement_id = _client_with_fixture(tmp_path)
    accepted = client.post(f"/projects/p1/entities/{requirement_id}/accept", json={"expected_revision": 1})
    assert accepted.status_code == 200
    locked = client.post(f"/projects/p1/entities/{requirement_id}/lock", json={"expected_revision": 2})
    assert locked.status_code == 200
    blocked = client.patch(f"/projects/p1/entities/{requirement_id}", json={"expected_revision": 3, "field_patch": {"name": "tampered"}})
    assert blocked.status_code == 409
    stale = client.post(f"/projects/p1/entities/{requirement_id}/unlock", json={"expected_revision": 2})
    assert stale.status_code == 409
    history = client.get("/projects/p1/history").json()
    assert history["metrics"]["revision_count"] == 3
    assert any(event["kind"] == "review.accept" for event in history["audit_events"])


def test_reanalysis_reports_request_without_claiming_execution(tmp_path):
    client, requirement_id = _client_with_fixture(tmp_path)

    response = client.post(f"/projects/p1/entities/{requirement_id}/reanalyze", json={"expected_revision": 1})

    assert response.status_code == 200
    request = response.json()["reanalysis"]
    assert request["status"] == "requested"
    assert request["execution_status"] == "pending_execution"
    assert request["execution_status_label"] == "已创建重新分析请求，尚未执行"
    assert request["lifecycle"] == ["requested", "pending_execution", "running", "completed", "failed", "cancelled"]


def test_requirement_detail_can_edit_statement_through_review_ui_contract(tmp_path):
    client, requirement_id = _client_with_fixture(tmp_path)

    edited = client.post(
        f"/projects/p1/entities/{requirement_id}/edit",
        json={"expected_revision": 1, "statement": "Battery shall last 10 hours"},
    )

    assert edited.status_code == 200
    assert edited.json()["review"]["status"] == "candidate"
    assert client.get(f"/projects/p1/requirements/{requirement_id}").json()["statement"] == "Battery shall last 10 hours"
    page = client.get(f"/ui/projects/p1/requirements/{requirement_id}")
    assert page.status_code == 200
    assert "保存编辑" in page.text
    assert "创建重新分析请求" in page.text


def test_accepted_requirement_detail_exposes_reject_and_lock(tmp_path):
    client, requirement_id = _client_with_fixture(tmp_path)
    assert client.post(f"/projects/p1/entities/{requirement_id}/accept", json={"expected_revision": 1}).status_code == 200

    page = client.get(f"/ui/projects/p1/requirements/{requirement_id}")

    assert page.status_code == 200
    assert 'data-action="reject"' in page.text
    assert 'data-action="lock"' in page.text
