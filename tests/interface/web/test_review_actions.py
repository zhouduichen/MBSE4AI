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
