from __future__ import annotations

from pathlib import Path

from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.methodology.contracts import StepStatus, TaskExecutionResponse
from rflp_lite.runtime.rule_based import VerticalRuleRuntime


def _services(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("p1")
    return services


def test_product_flow_returns_complete_rflp_and_bound_deliverable(tmp_path: Path):
    services = _services(tmp_path)

    result = services.product_flow("p1").run(
        "p1",
        requirement_text="系统应支持自主配送并允许人工接管",
    )

    assert result.status == "completed"
    assert result.generation["status"] == "completed"
    assert result.generation["traceability"]["end_to_end_complete_count"] >= 1
    assert result.deliverable["revision"] == result.revision
    assert result.deliverable["snapshot_hash"] == result.snapshot_hash
    assert result.concept == {"status": "not_requested"}
    assert result.cad == {"status": "not_requested"}
    assert "sysml" in result.deliverable["artifacts"]


def test_product_flow_translates_concept_missing_input(tmp_path: Path):
    services = _services(tmp_path)

    result = services.product_flow("p1").run(
        "p1",
        requirement_text="系统应满足总体布局约束",
        include_concept=True,
        optimize_concept=False,
    )

    assert result.status == "needs_input"
    assert result.concept["status"] == "needs_input"
    assert result.concept["input"]["status"] == "needs_input"
    assert result.deliverable["revision"] == result.revision


def test_product_flow_stops_at_cad_clarification(tmp_path: Path):
    services = _services(tmp_path)

    result = services.product_flow("p1").run(
        "p1",
        requirement_text="系统应支持详细结构设计",
        cad_intent_text="生成一个零件",
    )

    assert result.status == "needs_clarification"
    assert result.cad["status"] == "needs_clarification"
    assert result.cad["draft"]["status"] == "needs_clarification"
    assert result.deliverable["artifacts"]["detail_design"]["content"]["design_intent_drafts"]


def test_product_flow_stops_at_cad_approval_without_execution(tmp_path: Path):
    services = _services(tmp_path)

    result = services.product_flow("p1").run(
        "p1",
        requirement_text="系统应支持详细结构设计",
        cad_intent_text="生成铝合金支架，长100毫米，宽50毫米，高10毫米",
    )

    assert result.status == "needs_approval"
    assert result.cad["status"] == "needs_approval"
    assert result.cad["plan"]["approval_status"] == "pending"
    assert services.cad_design("p1").models() == ()
    assert result.deliverable["artifacts"]["detail_design"]["content"]["cad_execution_plans"]


def test_product_flow_carries_explicit_structure_selection_into_cad_plan(tmp_path: Path):
    services = _services(tmp_path)

    result = services.product_flow("p1").run(
        "p1",
        requirement_text="系统应支持详细结构设计",
        cad_intent_text="生成铝合金支架，长100毫米，宽50毫米，高10毫米",
        selected_structure_option_id="bracket-gusseted-plate",
    )

    plan = result.cad["plan"]
    assert result.status == "needs_approval"
    assert plan["selected_structure_option_id"] == "bracket-gusseted-plate"
    assert [item["operation"] for item in plan["operations"]].count("add_rib") == 2


def test_product_flow_stops_downstream_when_generation_fails(tmp_path: Path):
    class FailedRequirementsRuntime(VerticalRuleRuntime):
        def execute(self, request):
            if request.task_id == "vertical.requirements":
                return TaskExecutionResponse(
                    StepStatus.FAILED,
                    diagnostics=("injected generation failure",),
                )
            return super().execute(request)

    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=FailedRequirementsRuntime(),
    )
    services.projects.create("p1")

    result = services.product_flow("p1").run(
        "p1",
        requirement_text="系统应支持详细结构设计",
        cad_intent_text="生成铝合金支架，长100毫米，宽50毫米，高10毫米",
    )

    assert result.status == "failed"
    assert result.generation["status"] == "failed"
    assert result.concept == {"status": "not_requested"}
    assert result.cad == {"status": "not_requested"}
    assert services.cad_design("p1").drafts() == ()
    assert services.cad_design("p1").plans() == ()
