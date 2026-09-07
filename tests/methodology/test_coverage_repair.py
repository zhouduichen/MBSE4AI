from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.contracts import Phase
from rflp_lite.methodology.coverage import CoverageGap, CoverageReport, evaluate, is_saturated
from rflp_lite.methodology.repair import patch_for_plan, plan_repair


def test_empty_graph_routes_to_operational_local_candidate_repair():
    report = evaluate(ModelGraph("p1"))
    plan = plan_repair(report)

    assert plan.rollback_phase is Phase.OPERATIONAL
    assert plan.operations
    assert all(operation.entity.meta.status.value == "candidate" for operation in plan.operations)


def test_saturation_requires_two_low_yield_rounds():
    assert is_saturated((1, 0, 0)) is True
    assert is_saturated((0, 1)) is False


def test_repair_patch_uses_current_revision():
    graph = ModelGraph("p1")
    plan = plan_repair(CoverageReport((CoverageGap("missing_lifecycle", "lifecycle"),)))

    patch = patch_for_plan("p1", "repair.coverage", graph, plan)

    assert patch.expected_revision == 0
    assert patch.operations[0].entity.meta.kind.value == "lifecycle_stage"
