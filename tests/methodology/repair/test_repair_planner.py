from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.methodology.repair_context import RepairContext
from rflp_lite.methodology.repair_planner import classify_root_cause, plan


def _context(code):
    requirement = make_entity(EntityKind.REQUIREMENT, "需求", {"obligation": "支持配送"})
    return RepairContext("p1", "run-1", "issue-1", code, "F-Gate", (requirement.id,), 0, (requirement,), (), ())


def test_root_cause_classifier_is_deterministic():
    assert classify_root_cause("broken_requirement_function_trace") == "missing_relation_or_function"
    assert classify_root_cause("relation_endpoint_invalid") == "invalid_relation"
    assert classify_root_cause("semantic_invalid") == "invalid_entity_payload"


def test_missing_function_repair_is_narrow_and_bounded():
    task = plan(_context("missing_function"))

    assert task.target_task_id == "function_identification"
    assert task.writable_kinds == frozenset({EntityKind.FUNCTION})
    assert task.max_operations == 4
    assert task.as_task_spec(_context("missing_function")).patch_policy.max_operations == 4
