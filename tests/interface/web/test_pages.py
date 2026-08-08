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
    assert "MVP 已启用" in response.text
    assert "局部可用" in response.text
    assert "等待外部适配器" in response.text
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
    assert "场景描述" in page.text
    assert "RFLP 规划图" in page.text
    input_page = client.get("/w/demo/requirements/input")
    assert "规则分析已完成" in input_page.text
    assert "识别 2 条 Requirement 候选" in input_page.text
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
    assert "快速草稿图" in page.text
    assert "尚未经过人工确认" in page.text


def test_requirements_page_runs_one_click_flow_from_current_input(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})
    client.post(
        "/w/demo/requirements/analyze",
        data={"text": "管理员必须恢复历史版本。\n审计人员必须查看恢复记录。"},
    )

    completed = client.post("/w/demo/requirements/run-flow", follow_redirects=False)

    assert completed.status_code == 303
    page = client.get("/w/demo/requirements")
    assert "一键跑通需求闭环" in page.text
    assert "已完成" in page.text
    assert "project_validation · waiting_for_project_path" in page.text
    scenarios = client.get("/w/demo/requirements/scenarios")
    assert "根据需求“恢复历史版本”生成的最小可执行场景" in scenarios.text
    assert "declarative-only" in scenarios.text
    assert "<svg" in client.get("/w/demo/requirements/graph").text


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
    assert "暂无直接关联需求" in page.text

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
    assert "当前还没有需求文本" in page.text

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
    assert "关联 Requirement 可以之后再补" in page.text


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
