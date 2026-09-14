import json

import pytest

from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.architecture_reasoning import (
    logical_reasoning_payload,
    physical_reasoning_payload,
)
from rflp_lite.methodology.architecture_synthesis import synthesize_architecture
from rflp_lite.methodology.tasks import output_contract, task_catalog


def _graph():
    source = make_entity(EntityKind.FUNCTION, "采集", {"shared_state": ["任务状态"]})
    target = make_entity(
        EntityKind.FUNCTION,
        "调度",
        {"dependencies": [source.id], "shared_state": ["任务状态"]},
    )
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "功耗约束",
        {"constraints": {"max_power_w": 50}},
    )
    logical = make_entity(EntityKind.LOGICAL_COMPONENT, "任务控制器")
    physical = make_entity(EntityKind.PHYSICAL_BLOCK, "计算平台", {"power_w": 80})
    return ModelGraph(
        "robot",
        (source, target, requirement, logical, physical),
        (
            Relation("r-f", requirement.id, RelationPredicate.SATISFIED_BY, source.id),
            Relation("f-l", source.id, RelationPredicate.ALLOCATED_TO, logical.id),
            Relation("l-p", logical.id, RelationPredicate.ALLOCATED_TO, physical.id),
            Relation("r-p", requirement.id, RelationPredicate.SATISFIED_BY, physical.id),
        ),
    )


def test_logical_reasoning_payload_is_json_compatible_and_copies_candidates():
    graph = _graph()
    synthesis = synthesize_architecture(graph)
    function_ids = [item.id for item in graph.entities if item.kind is EntityKind.FUNCTION]

    payload = logical_reasoning_payload(
        synthesis,
        function_ids=function_ids,
        functional_flow_ids=[],
        dependency_pairs=[function_ids],
        shared_state=["任务状态"],
        timing_constraints=[],
        names={function_ids[0]: "采集", function_ids[1]: "调度"},
    )

    json.dumps(payload, ensure_ascii=False)
    assert payload["recommended_alternative"]
    assert payload["selection_status"] == "needs_review"
    assert payload["alternatives"]
    payload["alternatives"][0]["partitions"].clear()
    assert synthesis.logical_candidates[0].partitions


def test_physical_reasoning_payload_preserves_conflict_resolution_metadata():
    row = synthesize_architecture(_graph()).physical_rows[0]

    payload = physical_reasoning_payload(row)

    assert payload["status"] == "infeasible"
    assert payload["requirement_ids"]
    assert payload["logical_ids"]
    assert {item["reentry_stage"] for item in payload["resolution_options"]} >= {
        "physical", "requirements",
    }
    assert all(item["requires_user_decision"] for item in payload["resolution_options"])


def test_reasoning_contract_rejects_unknown_selection_and_cross_scope_dependency():
    synthesis = synthesize_architecture(ModelGraph("robot"))

    with pytest.raises(ContractViolation, match="selection status"):
        logical_reasoning_payload(
            synthesis,
            function_ids=[],
            functional_flow_ids=[],
            dependency_pairs=[],
            shared_state=[],
            timing_constraints=[],
            selection_status="unknown",
        )

    with pytest.raises(ContractViolation, match="reference function_ids"):
        logical_reasoning_payload(
            synthesis,
            function_ids=["function-a"],
            functional_flow_ids=[],
            dependency_pairs=[["function-a", "function-b"]],
            shared_state=[],
            timing_constraints=[],
        )


def test_structured_logical_and_physical_contracts_accept_reasoning_objects():
    logical_task = next(item for item in task_catalog() if item.id == "logical_analysis")
    physical_task = next(item for item in task_catalog() if item.id == "physical_candidates")
    logical_payload = output_contract(logical_task)["properties"]["entities"]["items"]["properties"]["payload"]
    physical_payload = output_contract(physical_task)["properties"]["entities"]["items"]["properties"]["payload"]

    assert logical_payload["additionalProperties"] is False
    assert logical_payload["properties"]["architecture_reasoning"] == {"type": "object"}
    assert physical_payload["properties"]["feasibility_reasoning"] == {"type": "object"}
    assert "oneOf" in logical_payload["properties"]["timing_constraints"]["items"]
    assert "oneOf" in logical_payload["properties"]["safety_isolation"]["items"]

    from jsonschema import validate

    validate({
        "timing_constraints": [{
            "id": "mission-cycle",
            "function_ids": ["function-a", "function-b"],
            "deadline_ms": 100,
        }],
        "safety_isolation": [{
            "function_ids": ["function-a", "function-b"],
            "must_separate": True,
        }],
    }, logical_payload)
