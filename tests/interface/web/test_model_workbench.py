from tests.interface.web.test_requirements_workbench import _client_with_fixture


def test_model_page_exposes_layered_entities_and_review_controls(tmp_path):
    client, _ = _client_with_fixture(tmp_path)

    page = client.get("/ui/projects/p1/model")

    assert page.status_code == 200
    assert "Functional" in page.text
    assert "Logical" in page.text
    assert "Physical" in page.text
    assert "V&amp;V" in page.text
    assert 'data-action="edit"' in page.text
    assert "Manage energy" in page.text
    assert "Battery pack" in page.text


def test_function_edit_keeps_id_marks_user_change_and_lock_protects_it(tmp_path):
    client, _ = _client_with_fixture(tmp_path)
    model = client.get("/projects/p1/model").json()
    function = next(item for item in model["entities"] if item["kind"] == "function")

    edited = client.post(
        f"/projects/p1/entities/{function['id']}/edit",
        json={
            "expected_revision": model["revision"],
            "name": "Manage energy revised",
            "payload": function["payload"],
        },
    )

    assert edited.status_code == 200
    current = client.get("/projects/p1/model").json()
    changed = next(item for item in current["entities"] if item["id"] == function["id"])
    assert changed["producer"] == "user"
    assert changed["payload"]["user_modified"] is True
    assert current["revision"] == model["revision"] + 1

    accepted = client.post(
        f"/projects/p1/entities/{function['id']}/accept",
        json={"expected_revision": current["revision"]},
    )
    assert accepted.status_code == 200
    locked = client.post(
        f"/projects/p1/entities/{function['id']}/lock",
        json={"expected_revision": accepted.json()["revision"]["sequence"]},
    )
    assert locked.status_code == 200
    blocked = client.post(
        f"/projects/p1/entities/{function['id']}/edit",
        json={"expected_revision": locked.json()["revision"]["sequence"], "name": "tampered"},
    )
    assert blocked.status_code == 409
