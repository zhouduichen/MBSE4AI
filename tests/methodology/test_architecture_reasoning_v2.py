import json

from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.architecture_synthesis import synthesize_architecture


def _function_graph() -> ModelGraph:
    acquire = make_entity(
        EntityKind.FUNCTION,
        "采集",
        {"timing_constraints": ["mission-cycle"]},
        status=EntityStatus.VALIDATED,
    )
    actuate = make_entity(
        EntityKind.FUNCTION,
        "执行",
        {"timing_constraints": ["mission-cycle"]},
        status=EntityStatus.VALIDATED,
    )
    safety = {
        "id": "control-boundary",
        "function_ids": [acquire.id, actuate.id],
        "must_separate": True,
        "reason": "采集与执行必须隔离",
    }
    acquire = acquire.__class__(
        acquire.meta,
        {**acquire.payload, "safety_isolation": [safety]},
    )
    return ModelGraph("robot", (acquire, actuate), (), 0)


def test_timing_and_safety_evidence_reaches_logical_candidates():
    graph = _function_graph()
    result = synthesize_architecture(graph)
    isolated = next(
        item for item in result.logical_candidates
        if item.alternative == "one_component_per_function"
    )

    assert isolated.timing_constraint_count == 1
    assert isolated.timing_cut_count == 1
    assert isolated.safety_isolation_count == 1
    assert isolated.safety_violation_count == 0
    assert isolated.constraint_violations == ()
    json.dumps(result.as_dict(), ensure_ascii=False)


def test_shared_coordinator_reports_explicit_safety_violation():
    graph = _function_graph()
    result = synthesize_architecture(graph)
    shared = next(
        item for item in result.logical_candidates
        if item.alternative == "shared_coordinator"
    )

    assert shared.safety_isolation_count == 1
    assert shared.safety_violation_count == 1
    assert shared.constraint_violations[0]["kind"] == "safety_isolation"
    assert set(shared.constraint_violations[0]["function_ids"]) == {
        item.id for item in graph.entities
    }


def test_unstructured_safety_text_does_not_create_pair():
    graph = ModelGraph(
        "robot",
        (
            make_entity(
                EntityKind.FUNCTION,
                "采集",
                {"safety_isolation": ["必须隔离"]},
            ),
            make_entity(
                EntityKind.FUNCTION,
                "执行",
                {"safety_isolation": ["必须隔离"]},
            ),
        ),
    )

    result = synthesize_architecture(graph)

    assert all(item.safety_isolation_count == 0 for item in result.logical_candidates)
