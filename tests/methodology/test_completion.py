from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate
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

    assert len(result.checks) == 6
    assert {item["id"] for item in result.checks} == {
        "function_identification",
        "functional_decomposition",
        "functional_interaction",
        "functional_scenario",
        "functional_requirement",
        "requirement_coverage:functional",
    }
    assert "completion_semantic:functional_interaction" in result.issue_codes


def test_vertical_stage_checks_logical_and_physical_evidence_fields():
    function = make_entity(EntityKind.FUNCTION, "配送", {"decomposition": ["执行"]})
    logical = make_entity(
        EntityKind.LOGICAL_COMPONENT,
        "配送逻辑",
        {"cohesion": "high", "coupling": "controlled"},
    )
    physical = make_entity(
        EntityKind.PHYSICAL_BLOCK,
        "配送平台",
        {"propagated_constraints": {}, "source_requirement_ids": []},
    )
    graph = ModelGraph("p1", (function, logical, physical))

    logical_result = evaluate_vertical_stage(VerticalStage.LOGICAL, graph)
    physical_result = evaluate_vertical_stage(VerticalStage.PHYSICAL, graph)

    assert "completion_semantic:architecture_evaluation" in logical_result.issue_codes
    assert "completion_semantic:feasibility_selection" in physical_result.issue_codes


def test_functional_completion_requires_grounded_flow_endpoints():
    function = make_entity(
        EntityKind.FUNCTION,
        "配送",
        {"decomposition": ["执行配送"]},
    )
    flow = make_entity(
        EntityKind.FUNCTIONAL_FLOW,
        "配送结果流",
        {
            "source_function_ids": [function.id],
            "target_function_ids": ["function-missing"],
        },
    )
    graph = ModelGraph(
        "p1",
        (function, flow),
        (Relation("function-flow", function.id, RelationPredicate.EXCHANGES_WITH, flow.id),),
    )

    result = evaluate_vertical_stage(VerticalStage.FUNCTIONAL, graph)

    assert "completion_semantic:functional_interaction" in result.issue_codes
