from pathlib import Path

from fastapi.testclient import TestClient

from rflp_lite.interface.web.app import create_app


def test_analysis_page_shows_full_harness_workflow(tmp_path: Path) -> None:
    app = create_app(tmp_path / "workspaces")
    app.state.container.v2.settings.profiles.config_dir = tmp_path / "config"
    app.state.container.v2.settings.profiles.path = tmp_path / "config" / "llm-profiles.json"
    client = TestClient(app)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    response = client.get("/ui/projects/p1/analysis")
    assert response.status_code == 200
    for label in (
        "运行场景",
        "功能分析",
        "逻辑/物理架构",
        "验证与确认",
        "封版归档",
        "当前修订",
        "活动模型",
        "运行状态",
        "全局质量门禁",
        "证据",
        "尝试次数",
        "补丁",
        "校验",
        "输入需求",
        "提交需求",
        "上传文档",
        "定向修复",
        "封版归档",
        "离线规则模式",
        "失败层",
    ):
        assert label in response.text


def test_analysis_view_contains_chinese_module_cards(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    page = client.get("/ui/projects/p1/analysis")

    assert page.status_code == 200
    for title in (
        "利益相关方",
        "生命周期",
        "场景与用例",
        "需求分析",
        "功能分析",
        "逻辑/物理架构",
        "验证与确认",
        "证据与问题",
        "运行与审计",
    ):
        assert title in page.text
    assert "analysis-sidebar" in page.text
    assert 'id="requirement-input-form"' in page.text
    assert 'id="document-upload-form"' in page.text
    assert 'title="请先提交需求或上传文档"' in page.text


def test_analysis_cards_switch_detail_panels_without_navigation(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    page = client.get("/ui/projects/p1/analysis")

    assert 'data-module-id="stakeholders"' in page.text
    assert 'data-module-panel="stakeholders"' in page.text
    assert "aria-selected" in page.text
    assert "点击卡片查看详情" in page.text


def test_analysis_page_uses_chinese_labels_for_runtime_and_gate(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    page = client.get("/ui/projects/p1/analysis")

    assert "当前修订" in page.text
    assert "活动模型" in page.text
    assert "全局质量门禁" in page.text
    assert "Run full pipeline" not in page.text


def test_analysis_api_supports_pipeline_and_force_run(tmp_path: Path) -> None:
    app = create_app(tmp_path / "workspaces")
    app.state.container.v2.settings.profiles.config_dir = tmp_path / "config"
    app.state.container.v2.settings.profiles.path = tmp_path / "config" / "llm-profiles.json"
    client = TestClient(app)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    initial = client.get("/projects/p1/analysis")
    assert initial.status_code == 200
    payload = initial.json()
    assert payload["current_revision"] == 0
    assert payload["runtime"]["mode"] == "Offline Rule Mode"
    assert [item["name"] for item in payload["phases"]] == [
        "Operational",
        "Functional",
        "Logical/Physical",
        "Assurance",
        "Closure",
    ]

    assert client.post("/projects/p1/requirements", json={"text": "系统应支持人工接管"}).status_code == 200

    response = client.post(
        "/projects/p1/analysis",
        json={"mode": "pipeline", "force_run": True},
    )
    assert response.status_code == 200
    run = response.json()["run"]
    assert run["mode"] == "pipeline"
    assert run["force_run"] is True
    assert [item["phase"] for item in run["phase_results"]] == [
        "operational",
        "functional",
        "logical_physical",
        "assurance",
        "closure",
    ]
    assert "gate_results" in run

    refreshed = client.get("/projects/p1/analysis").json()
    assert refreshed["latest_run"]["run_id"] == run["run_id"]
    assert refreshed["global_gate"]["gate_id"] == "Global-Gate"


def test_single_phase_analysis_keeps_legacy_shape(tmp_path: Path) -> None:
    app = create_app(tmp_path / "workspaces")
    app.state.container.v2.settings.profiles.config_dir = tmp_path / "config"
    app.state.container.v2.settings.profiles.path = tmp_path / "config" / "llm-profiles.json"
    client = TestClient(app)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    assert client.post("/projects/p1/requirements", json={"text": "系统应支持人工接管"}).status_code == 200

    response = client.post(
        "/projects/p1/analysis",
        json={"phase": "operational"},
    )
    assert response.status_code == 200
    run = response.json()["run"]
    assert run["phase"] == "operational"
    assert "completed_tasks" in run
    assert "diagnostics" in run


def test_computed_gate_issue_can_start_targeted_repair(tmp_path: Path) -> None:
    app = create_app(tmp_path / "workspaces")
    app.state.container.v2.settings.profiles.config_dir = tmp_path / "config"
    app.state.container.v2.settings.profiles.path = tmp_path / "config" / "llm-profiles.json"
    client = TestClient(app)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    issues = client.get("/projects/p1/analysis").json()["gate_issues"]
    issue = next(item for item in issues if item["code"] == "missing_verification")
    response = client.post("/projects/p1/repair", json={"issue_id": issue["id"]})

    assert response.status_code == 200
    assert response.json()["repair"]["root_cause"] == "verification"
    assert "re_gate" in response.json()["repair"]
