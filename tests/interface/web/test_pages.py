from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rflp_lite.interface.web.app import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "workspaces"))


@pytest.fixture
def client_with_run(client: TestClient):
    created = client.post("/workspaces", data={"name": "demo"}, follow_redirects=False)
    assert created.status_code == 303
    run = client.post(
        "/w/demo/runs",
        data={"solver": "heuristic", "seed": "42"},
        headers={"HX-Request": "true"},
    )
    assert run.status_code == 204
    location = run.headers["HX-Redirect"]
    return client, "demo", location.rsplit("/", 1)[-1]


def test_web_creates_workspace_and_runs_real_pipeline(client: TestClient) -> None:
    created = client.post("/workspaces", data={"name": "demo"}, follow_redirects=False)
    assert created.status_code == 303
    assert created.headers["location"] == "/w/demo"
    run = client.post(
        "/w/demo/runs",
        data={"solver": "heuristic", "seed": "42"},
        headers={"HX-Request": "true"},
    )
    assert run.status_code == 204
    assert run.headers["HX-Redirect"].startswith("/w/demo/runs/")
    detail = client.get(run.headers["HX-Redirect"])
    assert "Artifact → TextSpan → Claim" in detail.text
    assert "passed" in detail.text.lower()


def test_run_form_rejects_invalid_seed_without_starting(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})
    response = client.post(
        "/w/demo/runs",
        data={"solver": "heuristic", "seed": "-1"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 422
    assert "Seed 必须是非负整数" in response.text


@pytest.mark.parametrize(
    ("suffix", "expected"),
    (
        ("model/artifacts", "TextSpan"),
        ("model/rflp", "Requirement"),
        ("decision/candidates", "Candidate"),
        ("decision/simulation", "trace_hash"),
        ("governance/baselines", "Baseline"),
        ("governance/tasks", "TaskContract"),
        ("governance/evidence", "Audit"),
    ),
)
def test_real_run_pages(client_with_run, suffix: str, expected: str) -> None:
    web_client, workspace, result_hash = client_with_run
    response = web_client.get(f"/w/{workspace}/runs/{result_hash}/{suffix}")
    assert response.status_code == 200
    assert expected in response.text


def test_download_is_allowlisted(client_with_run) -> None:
    web_client, workspace, result_hash = client_with_run
    good = web_client.get(
        f"/w/{workspace}/runs/{result_hash}/downloads/evidence.json"
    )
    assert good.status_code == 200
    assert good.headers["content-type"].startswith("application/json")
    escaped = web_client.get(
        f"/w/{workspace}/runs/{result_hash}/downloads/%2E%2E%2Fprofile.json"
    )
    assert escaped.status_code in {400, 404}


def test_capability_center_reports_local_mvp_and_external_limits(client: TestClient) -> None:
    response = client.get("/capabilities")
    assert response.status_code == 200
    for name in ("LLM / Ollama", "Docling", "SysML v2", "MLflow", "登录与权限"):
        assert name in response.text
    assert "已启用" in response.text
    assert "局部可用" in response.text
    assert "未配置" in response.text
    assert "disabled" in response.text
    assert "模拟结果" not in response.text


def test_requirements_page_runs_reviewed_rflp_flow(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})
    analyzed = client.post(
        "/w/demo/requirements/analyze",
        data={
            "text": "管理员必须恢复历史版本。\n审计人员必须查看恢复记录。"
        },
        follow_redirects=False,
    )
    assert analyzed.status_code == 303
    client.post("/w/demo/requirements/accept-traceable")
    generated = client.post(
        "/w/demo/requirements/generate", follow_redirects=False
    )
    assert generated.status_code == 303

    page = client.get("/w/demo/requirements")

    assert page.status_code == 200
    assert "利益相关方" in page.text
    assert "场景生成与确认" in page.text
    assert "RFLP 规划图" in page.text
    input_page = client.get("/w/demo/requirements/input")
    assert "规则分析已完成" in input_page.text
    assert "需求候选 2" in input_page.text
    graph_page = client.get("/w/demo/requirements/graph")
    assert "<svg" in graph_page.text
    assert client.get("/w/demo/requirements/model.json").status_code == 200
    assert client.get("/w/demo/requirements/model.svg").status_code == 200
    assert client.get("/w/demo/requirements/model.sysml").status_code == 200


def test_requirements_page_can_generate_draft_without_review(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})
    client.post(
        "/w/demo/requirements/analyze",
        data={"text": "管理员必须恢复历史版本。"},
    )

    generated = client.post(
        "/w/demo/requirements/generate-draft", follow_redirects=False
    )

    assert generated.status_code == 303
    assert generated.headers["location"].endswith("/requirements/graph")
    page = client.get("/w/demo/requirements/graph")
    assert "需求理解图" in page.text
    assert "不能批准" in page.text
    assert "不是正式 RFLP" not in page.text
    assert "下一步：确认或修改" not in page.text


def test_plain_language_can_confirm_and_generate_formal_rflp_directly(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})
    client.post(
        "/w/demo/requirements/analyze",
        data={"text": "设置一个航天系统"},
    )

    generated = client.post(
        "/w/demo/requirements/confirm-and-generate", follow_redirects=False
    )

    assert generated.status_code == 303
    assert generated.headers["location"].endswith("/requirements/graph")
    page = client.get("/w/demo/requirements/graph")
    assert "正式 RFLP 模型已生成" in page.text
    assert "需求理解图" not in page.text
    assert "R" in page.text and "F" in page.text and "L" in page.text and "P" in page.text


def test_requirements_input_keeps_plain_language_as_a_candidate(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})
    client.post(
        "/w/demo/requirements/analyze",
        data={"text": "希望系统支持历史版本恢复。"},
    )

    page = client.get("/w/demo/requirements/input")

    assert "需求候选 1" in page.text
    assert "确认并生成 RFLP" in page.text


def test_requirement_review_uses_local_row_updates_and_direct_generation(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})
    client.post(
        "/w/demo/requirements/analyze",
        data={"text": "管理员必须恢复历史版本。"},
    )

    page = client.get("/w/demo/requirements/review")

    assert "hx-post=\"/w/demo/requirements/review\"" in page.text
    assert "hx-target=\"this\"" in page.text
    assert "确认并生成 RFLP" in page.text


def test_stakeholder_category_is_visible_and_editable(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})
    client.post(
        "/w/demo/requirements/analyze",
        data={"text": "管理员必须恢复历史版本。\n审计人员必须查看恢复记录。"},
    )

    page = client.get("/w/demo/requirements/stakeholders")
    assert "操作 / 运维" in page.text
    assert "监管 / 标准 / 审计" in page.text
    assert 'name="category"' in page.text

    review = client.get("/w/demo/requirements/review")
    assert "利益相关方类别" in review.text

    state = client.get("/api/v1/workspaces/demo/requirements").json()["requirements"]
    stakeholder = next(item for item in state["stakeholders"] if item["name"] == "管理员")
    updated = client.post(
        "/w/demo/requirements/review",
        data={
            "group": "stakeholders",
            "item_id": stakeholder["id"],
            "status": "accepted",
            "value": "管理员",
            "category": "customer",
        },
        headers={"HX-Request": "true"},
    )
    assert updated.status_code == 200
    refreshed = client.get("/api/v1/workspaces/demo/requirements").json()["requirements"]
    changed = next(item for item in refreshed["stakeholders"] if item["id"] == stakeholder["id"])
    assert changed["category"] == "customer"
    assert changed["status"] == "accepted"


def test_requirements_page_runs_one_click_flow_from_current_input(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})
    client.post(
        "/w/demo/requirements/analyze",
        data={"text": "管理员必须恢复历史版本。\n审计人员必须查看恢复记录。"},
    )

    completed = client.post("/w/demo/requirements/run-flow", follow_redirects=False)

    assert completed.status_code == 303
    page = client.get("/w/demo/requirements")
    assert "需求模型已建立" in page.text
    assert "正式模型" in page.text
    scenarios = client.get("/w/demo/requirements/scenarios")
    assert "根据需求“恢复历史版本”生成的最小可执行场景" in scenarios.text
    assert "确认场景" in scenarios.text
    assert "<svg" in client.get("/w/demo/requirements/graph").text


def test_scenario_page_generates_output_without_manual_scenario_fields(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})
    client.post(
        "/w/demo/requirements/analyze",
        data={"text": "设置一个航天系统"},
    )

    page = client.get("/w/demo/requirements/scenarios")

    assert page.status_code == 200
    assert "场景生成与确认" in page.text
    assert "场景必须先确认" in page.text
    assert "系统草稿" in page.text
    assert "航天系统" in page.text
    assert "必须先确认" in page.text
    assert "手动新增场景" in page.text
    payload = client.get("/w/demo/requirements/scenarios.json").json()
    assert len(payload) == 1
    assert payload[0]["producer"] == "system"


def test_project_requirement_overview_keeps_submitted_history_and_statuses(
    client: TestClient,
) -> None:
    client.post("/workspaces", data={"name": "demo"})
    client.post(
        "/w/demo/requirements/analyze",
        data={"text": "管理员必须恢复历史版本。"},
    )
    first = client.get("/api/v1/workspaces/demo/requirements").json()["requirements"]
    first_id = first["claims"][0]["id"]
    client.post(
        "/w/demo/requirements/review",
        data={
            "group": "claims",
            "item_id": first_id,
            "status": "rejected",
            "value": "管理员必须恢复历史版本。",
        },
    )
    client.post(
        "/w/demo/requirements/analyze",
        data={"text": "系统要有高鲁棒性。"},
    )

    overview = client.get("/api/v1/workspaces/demo/requirements/overview")
    assert overview.status_code == 200
    body = overview.json()["overview"]
    assert body["submitted"] == 2
    assert body["counts"]["rejected"] == 1
    assert body["counts"]["candidate"] == 1
    assert any(item["id"] == first_id and item["status"] == "rejected" for item in body["items"])

    page = client.get("/w/demo/requirements/overview")
    assert page.status_code == 200
    assert "项目需求概览" in page.text
    assert "管理员必须恢复历史版本" in page.text
    assert "系统要有高鲁棒性" in page.text
    assert "已驳回" in page.text


def test_formal_pages_omit_developer_facing_explanations(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})
    overview = client.get("/w/demo/requirements/overview")
    assert overview.status_code == 200
    assert "项目需求概览" in overview.text
    assert "不会因为你换了一次当前输入就丢失历史记录" not in overview.text

    pages = (
        "/w/demo",
        "/w/demo/requirements",
        "/w/demo/requirements/input",
        "/w/demo/requirements/review",
        "/w/demo/requirements/scenarios",
        "/w/demo/requirements/graph",
        "/w/demo/project",
        "/w/demo/runs",
        "/capabilities",
        "/settings/llm",
    )
    for path in pages:
        page = client.get(path)
        assert page.status_code == 200, path
        assert "不会因为你换了一次当前输入就丢失历史记录" not in page.text
        assert "Legacy demo execution" not in page.text


def test_system_input_produces_visible_rflp_svg_on_project_dashboard(
    client: TestClient,
) -> None:
    client.post("/workspaces", data={"name": "demo"})
    client.post(
        "/w/demo/requirements/analyze",
        data={"text": "设置一个航天系统"},
    )

    dashboard = client.get("/w/demo")
    assert dashboard.status_code == 200
    assert "航天系统 · 需求理解图" in dashboard.text
    assert "<svg" in dashboard.text
    svg = client.get("/w/demo/requirements/model.svg")
    assert svg.status_code == 200
    assert svg.headers["content-type"].startswith("image/svg+xml")
    assert "航天系统" in svg.text
    assert "需求理解图" in svg.text


def test_guided_path_separates_understanding_confirmation_and_formal_model(
    client: TestClient,
) -> None:
    client.post("/workspaces", data={"name": "demo"})
    client.post(
        "/w/demo/requirements/analyze",
        data={"text": "设置一个航天系统"},
    )

    draft_page = client.get("/w/demo/requirements")
    assert "确认系统对你的理解" in draft_page.text
    assert "一键跑通需求闭环" not in draft_page.text

    confirmed = client.post(
        "/w/demo/requirements/accept-traceable", follow_redirects=False
    )
    assert confirmed.status_code == 303
    review_page = client.get("/w/demo/requirements/review")
    assert "生成正式 RFLP" in review_page.text

    generated = client.post(
        "/w/demo/requirements/generate", follow_redirects=False
    )
    assert generated.status_code == 303
    formal_page = client.get("/w/demo/requirements/graph")
    assert "正式 RFLP 模型已生成" in formal_page.text
    assert "需求理解图" not in formal_page.text
    assert "正式 RFLP" in formal_page.text


def test_stakeholder_page_adds_role_and_shows_related_requirements(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})
    client.post(
        "/w/demo/requirements/analyze",
        data={"text": "管理员必须恢复历史版本。"},
    )

    added = client.post(
        "/w/demo/requirements/stakeholders",
        data={"name": "产品负责人"},
        follow_redirects=False,
    )
    assert added.status_code == 303
    page = client.get(
        "/w/demo/requirements/stakeholders?name=%E4%BA%A7%E5%93%81%E8%B4%9F%E8%B4%A3%E4%BA%BA"
    )
    assert "产品负责人" in page.text
    assert "暂无关联" in page.text

    detected = client.get("/w/demo/requirements/stakeholders?name=管理员")
    assert "管理员" in detected.text
    assert "管理员必须恢复历史版本" in detected.text
    assert "故障恢复" in detected.text


def test_stakeholder_page_can_start_before_requirements(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})

    added = client.post(
        "/w/demo/requirements/stakeholders",
        data={"name": "运维人员"},
        follow_redirects=False,
    )

    assert added.status_code == 303
    page = client.get("/w/demo/requirements/stakeholders?name=运维人员")
    assert "运维人员" in page.text
    assert "暂无需求文本" in page.text

    client.post(
        "/w/demo/requirements/analyze",
        data={"text": "管理员必须恢复历史版本。"},
    )
    preserved = client.get("/w/demo/requirements/stakeholders?name=运维人员")
    assert "运维人员" in preserved.text


def test_scenario_page_can_start_before_requirements(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})

    response = client.post(
        "/w/demo/requirements/scenarios",
        data={
            "title": "快速恢复",
            "description": "先描述流程，再补需求关联。",
            "steps": "选择版本\n确认恢复",
            "expected_outcomes": "恢复成功",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    page = client.get("/w/demo/requirements/scenarios")
    assert "快速恢复" in page.text
    assert "确认场景" in page.text


def test_requirements_page_creates_and_exports_scenario(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})
    client.post(
        "/w/demo/requirements/analyze",
        data={"text": "管理员必须恢复历史版本。"},
    )
    response = client.post(
        "/w/demo/requirements/scenarios",
        data={
            "title": "管理员恢复历史版本",
            "description": "管理员在版本存在时恢复历史内容。",
            "actors": "管理员\n内容服务",
            "preconditions": "历史版本存在",
            "steps": "选择历史版本\n确认恢复",
            "expected_outcomes": "内容恢复\n写入审计记录",
            "faults": "恢复失败时重试一次",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = client.get("/w/demo/requirements/scenarios")
    assert "管理员恢复历史版本" in page.text
    assert "场景描述" in page.text
    exported = client.get("/w/demo/requirements/scenarios.json")
    assert exported.status_code == 200
    assert "管理员恢复历史版本" in exported.text


def test_requirements_page_executes_scenario_and_exports_trace(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})
    client.post(
        "/w/demo/requirements/analyze",
        data={"text": "管理员必须恢复历史版本。"},
    )
    client.post(
        "/w/demo/requirements/scenarios",
        data={
            "title": "恢复历史版本",
            "description": "验证恢复流程",
            "steps": "选择版本\n确认恢复",
            "expected_outcomes": "内容恢复",
        },
    )
    state = client.get("/w/demo/requirements/scenarios.json").json()
    scenario_id = state[0]["id"]

    reviewed = client.post(
        "/w/demo/requirements/scenarios/review",
        data={"scenario_id": scenario_id, "decision": "accepted"},
        follow_redirects=False,
    )
    assert reviewed.status_code == 303

    response = client.post(
        "/w/demo/requirements/scenarios/execute",
        data={"scenario_id": scenario_id},
        follow_redirects=False,
    )

    assert response.status_code == 303
    page = client.get("/w/demo/requirements/scenarios")
    assert "生成执行轨迹" in page.text
    assert "declarative-only" in page.text
    runs = client.get("/w/demo/requirements/scenario-runs.json")
    assert runs.status_code == 200
    assert scenario_id in runs.text
