from pathlib import Path

from rflp_lite.application.engineering_tools import ToolExecutionRequest, ToolExecutionResult
from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import AddEntity, Patch, Relate
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.runtime.rule_based import VerticalRuleRuntime


_COMPLETE_PHYSICAL = {
    "mass_kg": 10,
    "power_w": 40,
    "compute": "8 cores",
    "memory_mb": 1024,
    "latency_ms": 10,
    "bandwidth_mbps": 100,
    "cost": 1000,
    "thermal": "pass",
    "reliability": "0.99",
    "availability": "0.99",
    "endurance_h": 12,
}


def _seed_case(services, *, physical_payload=None):
    project_id = "robot"
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "功耗约束",
        {"constraints": {"max_power_w": 50}},
    )
    physical = make_entity(
        EntityKind.PHYSICAL_BLOCK,
        "计算平台",
        physical_payload or _COMPLETE_PHYSICAL,
    )
    verification = make_entity(
        EntityKind.VERIFICATION_CASE,
        "验证功耗约束",
        {"requirement_ids": [requirement.id], "method": "analysis", "pass_criteria": "满足功耗约束"},
    )
    graph = services.model(project_id).graph(project_id)
    operations = tuple(
        [AddEntity(requirement), AddEntity(physical), AddEntity(verification)]
        + [
            Relate(requirement.id, RelationPredicate.SATISFIED_BY, physical.id),
            Relate(requirement.id, RelationPredicate.VERIFIED_BY, verification.id),
        ]
    )
    patch = Patch.create(project_id, "test.seed_tool_case", operations, "建立工程工具测试模型", graph.revision)
    services.model(project_id).apply_patch(project_id, patch, graph.revision)
    return verification


def test_model_constraint_tool_passes_only_when_complete_candidate_is_feasible(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")
    verification = _seed_case(services)

    result = services.tools("robot").execute("robot", verification.id, "model.constraint_check")

    assert result.outcome == "passed"
    assert result.metadata["measurement"] is False
    assert result.metadata["physical_ids"]
    evidence = services.repository("robot").list_evidence("robot")
    assert evidence[0]["source_type"] == "model_constraint_analysis"


def test_model_constraint_tool_routes_conflict_to_vv_issue(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")
    verification = _seed_case(services, physical_payload={**_COMPLETE_PHYSICAL, "power_w": 80})

    result = services.tools("robot").execute("robot", verification.id, "model.constraint_check")

    assert result.outcome == "failed"
    assert result.controller["next_action"]["task_id"] == "function_identification"
    assert any(item["code"] == "verification_execution_failed" for item in services.model("robot").issues("robot"))


def test_model_constraint_tool_is_inconclusive_when_measurement_is_missing(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")
    verification = _seed_case(services, physical_payload={**_COMPLETE_PHYSICAL, "power_w": None})

    result = services.tools("robot").execute("robot", verification.id, "model.constraint_check")

    assert result.outcome == "inconclusive"
    assert "needs_measurement" in result.excerpt
    assert result.metadata["measurement"] is False


class _ExternalSimulationTool:
    tool_id = "fixture.simulation"
    description = "测试用仿真适配器"
    case_kinds = (EntityKind.VALIDATION_CASE.value,)

    def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        assert request.parameters["scenario"] == "nominal"
        return ToolExecutionResult(
            "passed",
            "外部仿真在标称场景下通过。",
            "simulator result: pass",
            "simulator://run-001",
            "simulation_result",
            {"run_id": "run-001", "tool_version": "fixture-1"},
        )


def test_registered_external_tool_result_enters_vv_and_audit(tmp_path: Path):
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=VerticalRuleRuntime(),
        engineering_tools=(_ExternalSimulationTool(),),
    )
    services.projects.create("robot")
    requirement = make_entity(EntityKind.REQUIREMENT, "标称场景需求")
    validation = make_entity(EntityKind.VALIDATION_CASE, "标称场景确认")
    graph = services.model("robot").graph("robot")
    patch = Patch.create(
        "robot",
        "test.seed_external_tool",
        (
            AddEntity(requirement),
            AddEntity(validation),
            Relate(requirement.id, RelationPredicate.VALIDATED_BY, validation.id),
        ),
        "建立外部工具测试模型",
        graph.revision,
    )
    services.model("robot").apply_patch("robot", patch, graph.revision)

    descriptors = services.tools("robot").list_tools()
    result = services.tools("robot").execute(
        "robot",
        validation.id,
        "fixture.simulation",
        parameters={"scenario": "nominal"},
    )

    assert any(item["tool_id"] == "fixture.simulation" for item in descriptors)
    assert result.outcome == "passed"
    assert result.metadata["run_id"] == "run-001"
    assert any(
        item["kind"] == "engineering_tool.executed"
        and item["payload"]["tool_id"] == "fixture.simulation"
        for item in services.repository("robot").list_audit_events("robot")
    )
