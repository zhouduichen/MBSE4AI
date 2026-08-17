from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rflp_lite.interface.web.app import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    client = TestClient(create_app(tmp_path / "workspaces"))
    # Web page tests must not depend on a developer's configured local/remote
    # LLM.  The project-isolation assertions exercise persistence and scope,
    # not network availability.
    monkeypatch.setattr(client.app.state.facade, "_project_analysis_model", lambda: None)
    return client


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


def test_root_manages_multiple_projects_and_expands_requirements(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "alpha"})
    client.post(
        "/w/alpha/requirements/analyze",
        data={"text": "管理员必须恢复历史版本。"},
    )
    client.post("/workspaces", data={"name": "beta"})

    page = client.get("/")

    assert page.status_code == 200
    assert page.text.count('<details class="project-card">') == 2
    assert '<details class="project-card" open' not in page.text
    assert "alpha" in page.text and "beta" in page.text
    assert "管理员 必须 恢复历史版本" in page.text
    assert "/w/alpha/requirements" in page.text
    assert "暂无需求" in page.text


def test_requirement_delete_keeps_project_and_audit_history(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})
    client.post(
        "/w/demo/requirements/analyze",
        data={"text": "管理员必须恢复历史版本。"},
    )
    state = client.get("/api/v1/workspaces/demo/requirements").json()["requirements"]
    requirement_id = state["claims"][0]["id"]

    deleted = client.post(
        "/w/demo/requirements/delete",
        data={"requirement_id": requirement_id},
        follow_redirects=False,
    )

    assert deleted.status_code == 303
    assert deleted.headers["location"] == "/"
    after = client.get("/api/v1/workspaces/demo/requirements").json()["requirements"]
    assert after["claims"] == []
    assert after["scenarios"] == []
    assert after["rflp"] is None
    assert after["mbse"] is None
    assert "暂无需求" in client.get("/").text
    assert "已删除" in client.get("/w/demo/requirements/overview").text
    assert any(
        event["kind"] == "requirements.deleted"
        for event in client.app.state.facade.audit("demo")
    )


def test_requirement_workspaces_keep_analysis_and_history_isolated(
    client: TestClient,
) -> None:
    client.post("/workspaces", data={"name": "alpha"})
    client.post("/workspaces", data={"name": "beta"})

    alpha_response = client.post(
        "/w/alpha/requirements/analyze",
        data={"text": "调度员必须查看任务状态。"},
        follow_redirects=False,
    )
    beta_response = client.post(
        "/w/beta/requirements/analyze",
        data={"text": "维护员必须记录检修结果。"},
        follow_redirects=False,
    )

    assert alpha_response.status_code == 303
    assert beta_response.status_code == 303
    alpha = client.get("/api/v1/workspaces/alpha/requirements").json()["requirements"]
    beta = client.get("/api/v1/workspaces/beta/requirements").json()["requirements"]

    alpha_ids = {item["id"] for item in alpha["claims"]}
    beta_ids = {item["id"] for item in beta["claims"]}
    assert alpha_ids and beta_ids and alpha_ids.isdisjoint(beta_ids)
    assert "调度员" in alpha["claims"][0]["subject"]
    assert "维护员" in beta["claims"][0]["subject"]
    assert alpha["project_scope"]["workspace"] == "alpha"
    assert beta["project_scope"]["workspace"] == "beta"

    alpha_events = client.app.state.facade.audit("alpha")
    beta_events = client.app.state.facade.audit("beta")
    assert any(event["kind"] == "requirements.merged" for event in alpha_events)
    assert any(event["kind"] == "requirements.merged" for event in beta_events)
    assert all("维护员" not in str(event) for event in alpha_events)
    assert all("调度员" not in str(event) for event in beta_events)

    deleted = client.post(
        "/w/alpha/requirements/delete",
        data={"requirement_id": next(iter(alpha_ids))},
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    alpha_after = client.get("/api/v1/workspaces/alpha/requirements").json()["requirements"]
    beta_after = client.get("/api/v1/workspaces/beta/requirements").json()["requirements"]
    assert alpha_after["claims"] == []
    assert {item["id"] for item in beta_after["claims"]} == beta_ids
    assert any(
        event["kind"] == "requirements.deleted"
        for event in client.app.state.facade.audit("alpha")
    )
    assert not any(
        event["kind"] == "requirements.deleted"
        for event in client.app.state.facade.audit("beta")
    )


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
        ("decision/candidates", "候选与权衡"),
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
    assert "场景生成" in page.text
    assert "RFLP 规划图" in page.text
    input_page = client.get("/w/demo/requirements/input")
    assert "等待 LLM 分析" in input_page.text
    assert "需求 2" in input_page.text
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
    assert "草稿" in page.text
    assert "已理解内容" in page.text
    assert "回到需求输入" in page.text


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
    assert "RFLP 兼容模型已生成" in page.text
    assert "需求理解图" not in page.text
    assert "R" in page.text and "F" in page.text and "L" in page.text and "P" in page.text


def test_requirements_input_keeps_plain_language_as_a_candidate(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})
    client.post(
        "/w/demo/requirements/analyze",
        data={"text": "希望系统支持历史版本恢复。"},
    )

    page = client.get("/w/demo/requirements/input")

    assert "已纳入需求 1" in page.text
    assert "等待 LLM 分析" in page.text


def test_mbse_review_page_integrates_regeneration_and_state_labels(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})
    client.post(
        "/w/demo/requirements/analyze",
        data={"text": "管理员必须恢复历史版本。"},
    )
    client.post("/w/demo/requirements/accept-traceable")
    client.post("/w/demo/requirements/generate")

    generated = client.post("/w/demo/requirements/mbse", follow_redirects=False)
    assert generated.status_code == 303
    review_page = client.get("/w/demo/requirements/graph")
    assert "重新生成 MBSE 模型" in review_page.text
    assert 'action="/w/demo/requirements/mbse"' in review_page.text
    assert "已生成" in review_page.text
    assert "导出 JSON" in review_page.text

    model = client.get("/api/v1/workspaces/demo/requirements").json()["requirements"]["mbse"]
    assert model["status"] == "accepted"
    rejected = client.post(
        "/w/demo/requirements/mbse/review",
        data={"element_id": model["actors"][0]["id"], "decision": "rejected"},
        follow_redirects=False,
    )
    assert rejected.status_code == 303
    rejected_model = client.get("/api/v1/workspaces/demo/requirements").json()["requirements"]["mbse"]
    assert rejected_model["status"] == "review"
    assert any(item["status"] == "rejected" for item in rejected_model["actors"])
    rejected_page = client.get("/w/demo/requirements/graph")
    assert "需调整" in rejected_page.text
    assert "导出 JSON" not in rejected_page.text

    regenerated_for_review = client.post("/w/demo/requirements/mbse", follow_redirects=False)
    assert regenerated_for_review.status_code == 303
    model = client.get("/api/v1/workspaces/demo/requirements").json()["requirements"]["mbse"]
    assert model["status"] == "accepted"
    assert all(item["status"] == "accepted" for item in model["actors"])


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
    assert scenarios.text.count('class="scenario-card"') >= 2
    assert "展开详情" in scenarios.text
    assert "生成执行轨迹" in scenarios.text
    assert "<svg" in client.get("/w/demo/requirements/graph").text


def test_scenario_page_generates_output_without_manual_scenario_fields(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})
    client.post(
        "/w/demo/requirements/analyze",
        data={"text": "设置一个航天系统"},
    )

    page = client.get("/w/demo/requirements/scenarios")

    assert page.status_code == 200
    assert "场景生成" in page.text
    assert "当前项目场景" in page.text
    assert "未使用固定领域模板" not in page.text
    assert "手动新增场景" in page.text
    payload = client.get("/w/demo/requirements/scenarios.json").json()
    assert payload == []


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
    assert body["counts"]["accepted"] == 0
    assert any(item["id"] == first_id and item["status"] == "rejected" for item in body["items"])

    page = client.get("/w/demo/requirements/overview")
    assert page.status_code == 200
    assert "项目需求概览" in page.text
    assert "管理员必须恢复历史版本" in page.text
    assert "系统要有高鲁棒性" in page.text
    assert "已驳回" in page.text


def test_incremental_requirement_input_preserves_confirmed_state_and_shows_impact(
    client: TestClient,
) -> None:
    client.post("/workspaces", data={"name": "demo"})
    client.post(
        "/w/demo/requirements/analyze",
        data={"text": "管理员必须恢复历史版本。"},
    )
    client.post("/w/demo/requirements/confirm-and-generate")
    before = client.get("/api/v1/workspaces/demo/requirements").json()["requirements"]
    old_claim = before["claims"][0]
    old_stakeholder = before["stakeholders"][0]
    assert old_claim["status"] == "accepted"
    assert old_stakeholder["status"] == "accepted"

    client.post(
        "/w/demo/requirements/analyze",
        data={"text": "管理员必须查看修复历史。"},
    )
    after = client.get("/api/v1/workspaces/demo/requirements").json()["requirements"]
    claims = {item["object"]: item for item in after["claims"]}
    stakeholders = {item["name"]: item for item in after["stakeholders"]}

    assert claims["恢复历史版本"]["status"] == "accepted"
    assert claims["查看修复历史"]["status"] == "candidate"
    assert stakeholders["管理员"]["id"] == old_stakeholder["id"]
    assert stakeholders["管理员"]["status"] == "accepted"
    assert after["review_queue"]
    assert after["change_set"]["summary"]["requires_confirmation"] > 0

    review = client.get("/w/demo/requirements/review")
    assert "只确认本次新增或受影响的内容" in review.text
    assert "查看修复历史" in review.text
    assert "没有待确认内容" not in review.text

    from rflp_lite.adapters.sqlite_repository import SQLiteRepository

    repository = SQLiteRepository(client.app.state.facade.workspace("demo").path / ".rflp" / "model.db")
    try:
        revisions = repository.workbench_revisions()
    finally:
        repository.close()
    assert len(revisions) >= 3
    assert revisions[-1]["state"]["claims"]


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
    assert "航天系统" in dashboard.text
    assert "<svg" in dashboard.text
    svg = client.get("/w/demo/requirements/model.svg")
    assert svg.status_code == 200
    assert svg.headers["content-type"].startswith("image/svg+xml")
    assert "航天系统" in svg.text
    assert "DRAFT" in svg.text
    assert "STAKEHOLDER" not in svg.text


def test_guided_path_separates_understanding_confirmation_and_formal_model(
    client: TestClient,
) -> None:
    client.post("/workspaces", data={"name": "demo"})
    client.post(
        "/w/demo/requirements/analyze",
        data={"text": "设置一个航天系统"},
    )

    draft_page = client.get("/w/demo/requirements")
    assert "等待 LLM 分析" in client.get("/w/demo/requirements/input").text
    assert "需求模型已建立" not in draft_page.text
    formal_page = client.get("/w/demo/requirements/graph")
    assert "需求理解图" in formal_page.text
    assert "正式 RFLP" not in formal_page.text


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
    assert "已启用" in page.text


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


def test_mbse_design_page_renders_selectable_sequence_diagram(client: TestClient) -> None:
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
            "actors": "管理员\n数据库",
            "steps": "管理员 -> 系统：提交恢复请求\n系统 -> 数据库：查询历史版本\n系统 -> 管理员：返回恢复结果",
            "expected_outcomes": "内容恢复",
        },
    )
    scenario_id = client.get("/w/demo/requirements/scenarios.json").json()[0]["id"]
    reviewed = client.post(
        "/w/demo/requirements/scenarios/review",
        data={"scenario_id": scenario_id, "decision": "accepted"},
        follow_redirects=False,
    )
    assert reviewed.status_code == 303

    scenarios_page = client.get("/w/demo/requirements/scenarios")
    assert f"/requirements/mbse/sequence?scenario_id={scenario_id}" in scenarios_page.text

    page = client.get(
        "/w/demo/requirements/mbse/sequence",
        params={"scenario_id": scenario_id},
    )
    assert page.status_code == 200
    assert "MBSE 设计图" in page.text
    assert "选择场景" in page.text
    assert "sequence-svg" in page.text
    assert "marker-end=\"url(#arrow-filled)\"" in page.text
    assert "横向是参与者/系统边界" in page.text

    svg = client.get(
        "/w/demo/requirements/mbse/sequence.svg",
        params={"scenario_id": scenario_id},
    )
    assert svg.status_code == 200
    assert svg.headers["content-type"].startswith("image/svg+xml")
    assert "Sequence Diagram" in svg.text


def test_mbse_design_page_uses_clickable_module_cards(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})

    page = client.get("/w/demo/requirements/mbse?view=activity")

    assert page.status_code == 200
    assert page.text.count("diagram-module-card") == 4
    assert 'href="/w/demo/requirements/mbse?view=all"' in page.text
    assert 'href="/w/demo/requirements/mbse?view=use_case"' in page.text
    assert 'href="/w/demo/requirements/mbse?view=activity"' in page.text
    assert 'href="/w/demo/requirements/mbse/sequence"' in page.text
    assert "参与者与系统目标" in page.text
    assert "动作与控制流" in page.text
    assert "生命线与消息方向" in page.text
    assert 'class="diagram-module-card active"' in page.text


def test_sequence_diagram_keeps_unstructured_steps_as_candidate(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})
    client.post(
        "/w/demo/requirements/scenarios",
        data={
            "title": "未结构化场景",
            "description": "保留待确认语义",
            "steps": "选择版本\n确认恢复",
            "expected_outcomes": "内容恢复",
        },
    )
    scenario_id = client.get("/w/demo/requirements/scenarios.json").json()[0]["id"]
    client.post(
        "/w/demo/requirements/scenarios/review",
        data={"scenario_id": scenario_id, "decision": "accepted"},
    )

    page = client.get(
        "/w/demo/requirements/mbse/sequence",
        params={"scenario_id": scenario_id},
    )
    assert page.status_code == 200
    assert "语义提示" in page.text
    assert "candidate" in page.text
