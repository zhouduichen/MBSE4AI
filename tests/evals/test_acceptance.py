from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import ModelGraph
from rflp_lite.evals.acceptance import run_acceptance


def test_acceptance_report_is_model_only_and_has_no_project_execution_result():
    graph = ModelGraph("p1", (make_entity(EntityKind.SYSTEM, "校园无人配送机器人"),))
    report = run_acceptance(graph, {"system": "校园无人配送机器人"})
    value = report.as_dict()
    assert value["status"] == "passed"
    assert "returncode" not in value
    assert "project_execution" not in value
