from pathlib import Path

from fastapi.testclient import TestClient

from rflp_lite.application.llm_profiles import LLMProfileService
from rflp_lite.application.sysml_v2 import graph_to_sysml
from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import ModelGraph
from rflp_lite.interface.web.app import create_app
from rflp_lite.interface.web.resource_pages import _decorate_stage_result
from rflp_lite.runtime.rule_based import VerticalRuleRuntime


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
        "当前模型版本",
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
    assert 'title="请先提交需求、上传文档或导入已有模型"' in page.text


def test_analysis_page_exposes_secret_free_per_run_profile_selector(tmp_path: Path) -> None:
    app = create_app(tmp_path / "workspaces")
    config_dir = tmp_path / "config"
    app.state.container.v2.settings.profiles.config_dir = config_dir
    app.state.container.v2.settings.profiles.path = config_dir / "llm-profiles.json"
    profiles = LLMProfileService(config_dir)
    profiles.save({
        "id": "remote-profile",
        "label": "远程配置",
        "kind": "remote",
        "provider": "ollama",
        "base_url": "http://remote.example.invalid:11434/v1",
        "model": "qwen3.5:9b-q8_0",
        "api_key": "must-not-render",
    })
    client = TestClient(app)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    page = client.get("/ui/projects/p1/analysis")

    assert page.status_code == 200
    assert 'id="analysis-profile"' in page.text
    assert "远程配置" in page.text
    assert 'profile_id' in page.text
    assert "must-not-render" not in page.text


def test_analysis_page_exposes_existing_sysml_upload(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    page = client.get("/ui/projects/p1/analysis")

    assert page.status_code == 200
    assert "已有 SysML 模型" in page.text
    assert ".sysml" in page.text
    assert "/sysml/import/upload" in page.text


def test_analysis_page_enables_generation_after_partial_sysml_import(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    source = graph_to_sysml(
        ModelGraph(
            "source",
            (make_entity(EntityKind.FUNCTION, "已有配送功能"),),
            (),
            0,
        )
    )
    imported = client.post(
        "/projects/p1/sysml/import/upload",
        files={"file": ("partial.sysml", source, "text/plain")},
    )
    assert imported.status_code == 200

    page = client.get("/ui/projects/p1/analysis")

    assert page.status_code == 200
    assert 'data-mode="generate" disabled' not in page.text
    assert "导入模型也可以作为分析输入" in page.text


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

    assert "当前模型版本" in page.text
    assert "活动模型" in page.text
    assert "全局质量门禁" in page.text
    assert "Run full pipeline" not in page.text


def test_analysis_page_hides_harness_ledger_behind_advanced_diagnostics(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    page = client.get("/ui/projects/p1/analysis")

    assert page.status_code == 200
    assert "生成进度" in page.text
    assert "展开运行诊断（高级）" in page.text
    assert '<details class="advanced-details">' in page.text


def test_generated_analysis_page_uses_engineering_language_for_primary_summary(tmp_path: Path) -> None:
    app = create_app(tmp_path / "workspaces")
    app.state.container.v2._runtime_override = VerticalRuleRuntime()
    client = TestClient(app)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    generated = client.post(
        "/projects/p1/analysis",
        json={"mode": "generate", "requirement_text": "系统应支持人工接管"},
    )
    assert generated.status_code == 200

    page = client.get("/ui/projects/p1/analysis")

    assert page.status_code == 200
    for label in (
        "需求分析",
        "功能分析",
        "逻辑架构",
        "物理架构",
        "验证与确认",
        "工程检查",
        "逻辑分配覆盖",
        "物理方案状态",
        "验证与确认闭环",
        "补充执行证据",
    ):
        assert label in page.text
    assert "未配置模型" in page.text
    for internal_term in (
        "task_id",
        "vertical.physical",
        "collect_evidence",
        "trade_study",
        "physical_measurement_required",
        "Methodology Findings",
    ):
        assert internal_term not in page.text
    assert 'data-action-id="' in page.text


def test_generated_analysis_page_shows_requirement_coverage_summary(tmp_path: Path) -> None:
    app = create_app(tmp_path / "workspaces")
    app.state.container.v2._runtime_override = VerticalRuleRuntime()
    client = TestClient(app)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    assert client.post(
        "/projects/p1/requirements",
        json={"text": "系统应支持人工接管；系统应在断网后继续安全运行"},
    ).status_code == 200

    generated = client.post("/projects/p1/analysis", json={"mode": "generate"})

    assert generated.status_code == 200
    page = client.get("/ui/projects/p1/analysis")
    assert page.status_code == 200
    assert "逐条需求覆盖" in page.text
    assert "逐条需求覆盖完整" in page.text
    assert "requirement_coverage:" not in page.text


def test_explicit_pipeline_analysis_page_shows_unified_engineering_result(tmp_path: Path) -> None:
    app = create_app(tmp_path / "workspaces")
    app.state.container.v2._runtime_override = VerticalRuleRuntime()
    client = TestClient(app)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    assert client.post(
        "/projects/p1/requirements", json={"text": "系统应支持人工接管"}
    ).status_code == 200
    assert client.post(
        "/projects/p1/analysis",
        json={"mode": "generate"},
    ).status_code == 200

    pipeline = client.post("/projects/p1/analysis", json={"mode": "pipeline"})

    assert pipeline.status_code == 200
    assert pipeline.json()["run"]["mode"] == "pipeline"
    page = client.get("/ui/projects/p1/analysis")

    assert page.status_code == 200
    for label in (
        "完整生命周期结果",
        "工程检查",
        "逻辑架构候选",
        "物理可行性矩阵",
        "下一步工程动作",
    ):
        assert label in page.text


def test_stage_view_exposes_exact_requirement_coverage_gaps() -> None:
    stage = _decorate_stage_result(
        {
            "stage": "functional",
            "status": "needs_review",
            "completion_checks": [
                {
                    "id": "requirement_coverage:functional",
                    "stage": "functional",
                    "passed": False,
                    "missing_requirement_ids": ["requirement-2"],
                }
            ],
            "completion_issue_codes": ["completion_requirement_coverage:functional"],
        }
    )

    assert stage["requirement_coverage_summary"] == "1 条需求待补全"
    assert stage["requirement_coverage_missing_ids"] == ["requirement-2"]


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
    assert run["traceability"]
    assert run["methodology"]
    assert run["controller"]
    assert run["report_revision"] == run["deliverable"]["revision"]
    assert run["report_snapshot_hash"] == run["deliverable"]["snapshot_hash"]

    refreshed = client.get("/projects/p1/analysis").json()
    assert refreshed["latest_run"]["run_id"] == run["run_id"]
    assert refreshed["global_gate"]["gate_id"] == "Global-Gate"


def test_analysis_api_defaults_to_complete_vertical_generation(tmp_path: Path) -> None:
    app = create_app(tmp_path / "workspaces")
    app.state.container.v2.settings.profiles.config_dir = tmp_path / "config"
    app.state.container.v2.settings.profiles.path = tmp_path / "config" / "llm-profiles.json"
    client = TestClient(app)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    assert client.post(
        "/projects/p1/requirements", json={"text": "系统应支持人工接管"}
    ).status_code == 200

    response = client.post("/projects/p1/analysis", json={})

    assert response.status_code == 200
    run = response.json()["run"]
    assert run["mode"] == "generate"
    assert [item["stage"] for item in run["stage_results"]] == [
        "requirements", "functional", "logical", "physical", "verification_validation"
    ]
    assert "traceability" in run
    assert "methodology" in run
    assert "controller" in run


def test_pipeline_analysis_accepts_natural_language_input(tmp_path: Path) -> None:
    app = create_app(tmp_path / "workspaces")
    app.state.container.v2.settings.profiles.config_dir = tmp_path / "config"
    app.state.container.v2.settings.profiles.path = tmp_path / "config" / "llm-profiles.json"
    client = TestClient(app)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    response = client.post(
        "/projects/p1/analysis",
        json={"mode": "pipeline", "requirement_text": "系统应支持人工接管"},
    )

    assert response.status_code == 200
    graph = app.state.container.v2.repository("p1").load_graph("p1")
    assert any(item.payload.get("statement") == "系统应支持人工接管" for item in graph.entities)


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
