from tests.interface.web.test_requirements_workbench import _client_with_fixture
from rflp_lite.runtime.rule_based import VerticalRuleRuntime


def test_assurance_behavior_operational_and_history_pages_are_available(tmp_path):
    client, _ = _client_with_fixture(tmp_path)
    for path in ("/projects/p1/operational", "/projects/p1/behavior", "/projects/p1/assurance", "/projects/p1/history", "/ui/projects/p1/operational", "/ui/projects/p1/behavior", "/ui/projects/p1/assurance", "/ui/projects/p1/history"):
        assert client.get(path).status_code == 200


def test_assurance_page_exposes_controller_next_action_after_vv_failure(tmp_path):
    client, _ = _client_with_fixture(tmp_path, runtime=VerticalRuleRuntime())
    generated = client.post(
        "/projects/p1/analysis",
        json={"mode": "generate", "requirement_text": "系统应支持人工接管"},
    ).json()["run"]
    verification = next(
        item for item in client.get("/projects/p1/model").json()["entities"]
        if item["kind"] == "verification_case"
    )

    response = client.post(
        f"/projects/p1/vv/{verification['id']}/execute",
        json={
            "outcome": "failed",
            "claim": "接管响应超时",
            "excerpt": "测试日志：响应时间超过通过准则。",
            "expected_revision": generated["revision"],
        },
    )
    assert response.status_code == 200

    page = client.get("/ui/projects/p1/assurance")

    assert page.status_code == 200
    assert "系统工程下一步" in page.text
    assert "方案权衡" in page.text
    assert "task_id" not in page.text
    assert "重构受影响功能" in page.text


def test_assurance_page_renders_executable_vv_plan_fields(tmp_path):
    client, _ = _client_with_fixture(tmp_path)

    page = client.get("/ui/projects/p1/assurance")

    assert page.status_code == 200
    assert "测试条件" in page.text
    assert "刺激" in page.text
