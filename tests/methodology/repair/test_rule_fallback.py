from rflp_lite.domain.entities import EntityKind, Producer
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.repair_context import RepairContext
from rflp_lite.methodology.repair_planner import plan
from rflp_lite.methodology.repair_strategies import RuleFallbackRepairStrategy


def test_rule_fallback_marks_placeholder_as_rule_provenance_and_human_review():
    context = RepairContext("p1", "run-1", "issue-1", "missing_function", "F-Gate", (), 0, (), (), ())
    task = plan(context)

    proposal = RuleFallbackRepairStrategy().propose(ModelGraph("p1"), context, task)
    entity = proposal.patch.operations[0].entity

    assert proposal.strategy == "rule_fallback"
    assert entity.meta.producer is Producer.RULE
    assert entity.meta.status.value == "candidate"
    assert entity.payload["fallback_placeholder"] is True
    assert entity.payload["requires_human_review"] is True
