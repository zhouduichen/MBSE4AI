from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.completion import evaluate_completion, evaluate_vertical_stage
from rflp_lite.methodology.contracts import StepStatus, TaskExecutionResponse
from rflp_lite.methodology.tasks import task_catalog
from rflp_lite.methodology.vertical_generation import VerticalStage


def test_lifecycle_task_requires_its_named_semantic_output():
    task = next(item for item in task_catalog() if item.id == "functional_decomposition")
    function = make_entity(EntityKind.FUNCTION, "配送")
    response = TaskExecutionResponse(
        StepStatus.COMPLETED,
        diagnostics=("offline:lifecycle-idempotent",),
    )

    result = evaluate_completion(task, ModelGraph("p1", (function,)), response)

    assert not result.passed
    assert "completion_semantic:functional_decomposition" in result.issue_codes


def test_vertical_stage_reports_each_internal_task_and_failed_checks():
    function = make_entity(
        EntityKind.FUNCTION,
        "配送",
        {"decomposition": ["接收任务", "执行任务"]},
    )
    result = evaluate_vertical_stage(
        VerticalStage.FUNCTIONAL,
        ModelGraph("p1", (function,)),
    )

    assert len(result.checks) == 5
    assert {item["id"] for item in result.checks} == {
        "function_identification",
        "functional_decomposition",
        "functional_interaction",
        "functional_scenario",
        "functional_requirement",
    }
    assert "completion_semantic:functional_interaction" in result.issue_codes
