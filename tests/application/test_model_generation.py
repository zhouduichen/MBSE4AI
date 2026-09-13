from pathlib import Path

from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.domain.entities import EntityKind, Producer
from rflp_lite.runtime.rule_based import VerticalRuleRuntime


def test_generation_creates_real_rflp_and_vv_objects_from_one_requirement(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot", "校园配送机器人")

    result = services.generation("robot").generate(
        "robot",
        requirement_text="系统应在校园内自主完成配送并支持人工接管",
    )
    graph = services.model("robot").graph("robot")

    assert result.status == "completed"
    assert {
        EntityKind.FUNCTION,
        EntityKind.LOGICAL_COMPONENT,
        EntityKind.PHYSICAL_BLOCK,
        EntityKind.VERIFICATION_CASE,
        EntityKind.VALIDATION_CASE,
    } <= {item.kind for item in graph.entities}
    assert result.traceability.complete_count >= 1
    assert all(
        "候选" not in item.meta.name and "待确认" not in item.meta.name
        for item in graph.entities
        if item.meta.producer is Producer.RULE
    )


def test_generation_is_recorded_as_one_five_stage_run(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")

    result = services.generation("robot").generate(
        "robot", requirement_text="系统应支持人工接管"
    )
    run = services.repository("robot").load_run("robot", result.run_id)

    assert run is not None
    assert run.phase == "vertical_generation"
    assert {step.task_id for step in run.steps} == {
        "vertical.requirements",
        "vertical.functional",
        "vertical.logical",
        "vertical.physical",
        "vertical.verification_validation",
    }
    assert all(step.status == "completed" for step in run.steps)
