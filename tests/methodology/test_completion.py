from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.completion import evaluate_completion
from rflp_lite.methodology.contracts import StepStatus, TaskExecutionResponse
from rflp_lite.methodology.tasks import task_catalog


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
