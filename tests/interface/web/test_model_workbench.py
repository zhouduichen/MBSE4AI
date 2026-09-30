from tests.interface.web.test_requirements_workbench import _client_with_fixture
from rflp_lite.runtime.rule_based import VerticalRuleRuntime


def test_model_page_exposes_layered_entities_and_review_controls(tmp_path):
    client, _ = _client_with_fixture(tmp_path)

    page = client.get("/ui/projects/p1/model")

    assert page.status_code == 200
    assert "功能" in page.text
    assert "逻辑" in page.text
    assert "物理" in page.text
    assert "验证与确认" in page.text
    assert 'data-action="edit"' in page.text
    assert "查看影响分析" in page.text
    assert "/entities/" in page.text and "/impact" in page.text
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


def test_continue_generation_api_runs_only_downstream_stages(tmp_path):
    client, _ = _client_with_fixture(tmp_path, runtime=VerticalRuleRuntime())
    model = client.get("/projects/p1/model").json()
    function = next(item for item in model["entities"] if item["kind"] == "function")

    accepted = client.post(
        f"/projects/p1/entities/{function['id']}/accept",
        json={"expected_revision": model["revision"]},
    )
    assert accepted.status_code == 200
    accepted_revision = accepted.json()["revision"]["sequence"]

    response = client.post(
        f"/projects/p1/entities/{function['id']}/continue",
        json={"expected_revision": accepted_revision},
    )

    assert response.status_code == 200
    continuation = response.json()["continuation"]
    assert continuation["execution_status"] == "completed"
    assert continuation["selected_stages"] == [
        "logical", "physical", "verification_validation"
    ]


def test_model_workbench_exposes_continue_action_after_function_acceptance(tmp_path):
    client, _ = _client_with_fixture(tmp_path)
    model = client.get("/projects/p1/model").json()
    function = next(item for item in model["entities"] if item["kind"] == "function")
    accepted = client.post(
        f"/projects/p1/entities/{function['id']}/accept",
        json={"expected_revision": model["revision"]},
    )
    assert accepted.status_code == 200

    page = client.get("/ui/projects/p1/model")

    assert page.status_code == 200
    assert "继续生成下游" in page.text
    assert 'data-review-action="continue"' in page.text


def test_candidate_continue_is_rejected_until_acceptance(tmp_path):
    client, _ = _client_with_fixture(tmp_path, runtime=VerticalRuleRuntime())
    model = client.get("/projects/p1/model").json()
    function = next(item for item in model["entities"] if item["kind"] == "function")

    edited = client.post(
        f"/projects/p1/entities/{function['id']}/edit",
        json={"expected_revision": model["revision"], "name": "人工修改功能"},
    )
    assert edited.status_code == 200
    revision = edited.json()["revision"]["sequence"]
    blocked = client.post(
        f"/projects/p1/entities/{function['id']}/continue",
        json={"expected_revision": revision},
    )

    assert blocked.status_code == 422
    assert "accepted or locked" in blocked.json()["message"]


def test_vv_cards_do_not_expose_downstream_continue_action(tmp_path):
    client, _ = _client_with_fixture(tmp_path)
    model = client.get("/projects/p1/model").json()
    validation = next(item for item in model["entities"] if item["kind"] == "validation_case")
    accepted = client.post(
        f"/projects/p1/entities/{validation['id']}/accept",
        json={"expected_revision": model["revision"]},
    )
    assert accepted.status_code == 200

    page = client.get("/ui/projects/p1/model")

    assert page.status_code == 200
    assert 'data-review-action="continue"' not in page.text


def test_model_page_exposes_complete_delivery_panel(tmp_path):
    client, _ = _client_with_fixture(tmp_path)

    page = client.get("/ui/projects/p1/model")

    assert page.status_code == 200
    assert "导出完整交付包" in page.text
    assert "/projects/p1/deliverables/download" in page.text
    assert "snapshot" in page.text.lower()
