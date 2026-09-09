from rflp_lite.methodology.contracts import FailureAction
from rflp_lite.methodology.tasks import task_catalog
from rflp_lite.methodology.workflow import WorkflowRunner


def test_task_spec_declares_repair_route_for_requirement_function_gap():
    task = next(item for item in task_catalog() if item.id == "function_identification")
    route = next(item for item in task.failure_routes if item.issue_code == "broken_requirement_function_trace")

    assert route.action is FailureAction.REPAIR
    assert route.target_task_id == "function_identification"
    assert route.rollback_phase.value == "functional"


def test_legacy_issue_target_lookup_prefers_task_spec_route():
    runner = object.__new__(WorkflowRunner)

    assert runner._target_task_for_issue("broken_requirement_function_trace") == "function_identification"
