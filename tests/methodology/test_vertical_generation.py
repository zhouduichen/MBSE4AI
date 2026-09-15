from rflp_lite.domain.entities import EntityKind
from rflp_lite.methodology.contracts import ContextBundle
from rflp_lite.methodology.executor import TaskExecutor
from rflp_lite.methodology.vertical_generation import (
    VerticalStage,
    downstream_vertical_stages,
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
    assert {
        EntityKind.FUNCTION,
        EntityKind.FUNCTIONAL_FLOW,
        EntityKind.FUNCTIONAL_SCENARIO,
        EntityKind.REQUIREMENT,
    } <= stage_task(VerticalStage.FUNCTIONAL).patch_policy.writable_kinds


def test_downstream_routing_skips_the_confirmed_stage():
    assert [item.stage.value for item in downstream_vertical_stages(EntityKind.FUNCTION)] == [
        "logical", "physical", "verification_validation"
    ]
    assert downstream_vertical_stages(EntityKind.VALIDATION_CASE) == ()


def test_requirements_stage_requires_operational_model_kinds_and_internal_steps():
    requirements = next(item for item in vertical_stage_specs() if item.stage is VerticalStage.REQUIREMENTS)

    assert requirements.required_kinds == frozenset({
        EntityKind.SYSTEM,
        EntityKind.STAKEHOLDER,
        EntityKind.CONCERN,
        EntityKind.LIFECYCLE_STAGE,
        EntityKind.LIFECYCLE_TRANSITION,
        EntityKind.SCENARIO_HYPOTHESIS,
        EntityKind.USE_CASE,
        EntityKind.OPERATIONAL_SCENARIO,
        EntityKind.ACTIVITY,
        EntityKind.REQUIREMENT,
    })
    assert "lifecycle_analysis" in requirements.reasoning_tasks
    assert "activity_analysis" in requirements.reasoning_tasks


def test_logical_and_assurance_stages_require_state_and_risk_objects():
    specs = {item.stage: item for item in vertical_stage_specs()}

    assert EntityKind.STATE in specs[VerticalStage.LOGICAL].required_kinds
    assert EntityKind.STATE in specs[VerticalStage.LOGICAL].output_kinds
    assert {EntityKind.HAZARD, EntityKind.FAILURE_MODE} <= specs[
        VerticalStage.VERIFICATION_VALIDATION
    ].required_kinds


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


def test_vertical_prompts_require_mandatory_logical_state_and_assurance_risk_objects():
    logical = TaskExecutor(RuleRuntime()).request(
        stage_task(VerticalStage.LOGICAL),
        ContextBundle("p1", "vertical.logical", 0, ()),
        "v2.1",
    )
    assurance = TaskExecutor(RuleRuntime()).request(
        stage_task(VerticalStage.VERIFICATION_VALIDATION),
        ContextBundle("p1", "vertical.verification_validation", 0, ()),
        "v2.1",
    )

    assert "至少生成一个代表系统运行状态或功能状态机的 state 实体" in logical.prompt_text
    assert "无论资料是否显式给出风险，都至少生成一个 hazard 和一个 failure_mode" in assurance.prompt_text


def test_functional_contract_requires_traceable_behavior_payloads():
    request = TaskExecutor(RuleRuntime()).request(
        stage_task(VerticalStage.FUNCTIONAL),
        ContextBundle("p1", "vertical.functional", 0, ()),
        "v2.1",
    )
    schemas = request.output_contract["x-payload-schemas"]

    assert schemas[EntityKind.FUNCTION.value]["required"] == ["decomposition"]
    assert schemas[EntityKind.FUNCTIONAL_FLOW.value]["required"] == [
        "source_function_ids", "target_function_ids",
    ]
    assert schemas[EntityKind.FUNCTIONAL_SCENARIO.value]["required"] == ["function_ids"]
