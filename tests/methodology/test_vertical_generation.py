from rflp_lite.domain.entities import EntityKind
from rflp_lite.methodology.contracts import ContextBundle
from rflp_lite.methodology.executor import TaskExecutor
from rflp_lite.methodology.vertical_generation import (
    VerticalStage,
    stage_task,
    vertical_stage_specs,
)
from rflp_lite.runtime.rule_based import RuleRuntime


def test_vertical_stages_have_product_order_and_narrow_write_scopes():
    assert [item.stage for item in vertical_stage_specs()] == [
        VerticalStage.REQUIREMENTS,
        VerticalStage.FUNCTIONAL,
        VerticalStage.LOGICAL,
        VerticalStage.PHYSICAL,
        VerticalStage.VERIFICATION_VALIDATION,
    ]
    assert stage_task(VerticalStage.FUNCTIONAL).patch_policy.writable_kinds == frozenset({
        EntityKind.FUNCTION,
        EntityKind.FUNCTIONAL_FLOW,
        EntityKind.FUNCTIONAL_SCENARIO,
    })


def test_requirements_stage_requires_operational_model_kinds_and_internal_steps():
    requirements = next(item for item in vertical_stage_specs() if item.stage is VerticalStage.REQUIREMENTS)

    assert requirements.required_kinds == frozenset({
        EntityKind.SYSTEM,
        EntityKind.STAKEHOLDER,
        EntityKind.LIFECYCLE_STAGE,
        EntityKind.SCENARIO_HYPOTHESIS,
        EntityKind.USE_CASE,
        EntityKind.OPERATIONAL_SCENARIO,
        EntityKind.ACTIVITY,
        EntityKind.REQUIREMENT,
    })
    assert "lifecycle_analysis" in requirements.reasoning_tasks
    assert "activity_analysis" in requirements.reasoning_tasks


def test_vertical_prompt_resources_resolve_and_include_review_metadata():
    task = stage_task(VerticalStage.PHYSICAL)
    request = TaskExecutor(RuleRuntime()).request(
        task,
        ContextBundle("p1", task.id, 0, ()),
        "v2.1",
    )

    assert request.prompt_version == "v1"
    assert "物理架构工程师" in request.prompt_text
    assert request.output_contract["properties"]["assumptions"]["type"] == "array"
