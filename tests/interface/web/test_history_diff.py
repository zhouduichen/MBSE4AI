from tests.interface.web.test_requirements_workbench import _client_with_fixture


def test_revision_diff_exposes_user_review_changes(tmp_path):
    client, requirement_id = _client_with_fixture(tmp_path)
    result = client.post(f"/projects/p1/entities/{requirement_id}/accept", json={"expected_revision": 1})
    assert result.status_code == 200
    diff = client.get("/projects/p1/revisions/2/diff")
    assert diff.status_code == 200
    assert any(item["id"] == requirement_id for item in diff.json()["diff"]["updated_entities"])
