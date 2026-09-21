from dataclasses import replace

from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.closure import evaluate_strict_closure
from rflp_lite.methodology.coverage_matrix import build_requirement_coverage
from rflp_lite.methodology.gates import global_gate, rflp_gate


def _graph(*, requirement_status=EntityStatus.ACCEPTED, omit=(), requirement_payload=None):
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "配送需求",
        {"obligation": "支持配送", "evidence_ids": ["e1"], **(requirement_payload or {})},
        status=requirement_status,
        evidence_ids=("e1",),
    )
    function = make_entity(EntityKind.FUNCTION, "支持配送", status=EntityStatus.VALIDATED)
    logical = make_entity(EntityKind.LOGICAL_COMPONENT, "配送逻辑", status=EntityStatus.VALIDATED)
    physical = make_entity(EntityKind.PHYSICAL_BLOCK, "配送执行器", status=EntityStatus.VALIDATED)
    vv_payload = {
        "requirement_ids": [requirement.id],
        "function_ids": [function.id],
        "logical_component_ids": [logical.id],
        "physical_ids": [physical.id],
        "method": "test",
        "verification_objective": "证明需求满足",
        "precondition": "系统可用",
        "test_condition": "标准条件",
        "input": "配送任务",
        "stimulus": "提交任务",
        "procedure": "执行任务并记录结果",
        "expected_result": "任务完成",
        "pass_criteria": "结果满足需求",
    }
    verification = make_entity(
        EntityKind.VERIFICATION_CASE,
        "验证配送需求",
        vv_payload,
        status=EntityStatus.VALIDATED,
    )
    validation = make_entity(
        EntityKind.VALIDATION_CASE,
        "确认配送需求",
        {**vv_payload, "method": "demonstration"},
        status=EntityStatus.VALIDATED,
    )
    entities = {
        "requirement": requirement,
        "function": function,
        "logical": logical,
        "physical": physical,
        "verification": verification,
        "validation": validation,
    }
    relations = (
        Relation("r-f", requirement.id, RelationPredicate.SATISFIED_BY, function.id),
        Relation("f-l", function.id, RelationPredicate.ALLOCATED_TO, logical.id),
        Relation("l-p", logical.id, RelationPredicate.REALIZED_BY, physical.id),
        Relation("r-v", requirement.id, RelationPredicate.VERIFIED_BY, verification.id),
        Relation("r-val", requirement.id, RelationPredicate.VALIDATED_BY, validation.id),
    )
    return ModelGraph(
        "p1",
        tuple(entity for key, entity in entities.items() if key not in set(omit)),
        tuple(
            relation for relation in relations
            if relation.source_id in {entity.id for entity in entities.values() if entity.id not in {entities[key].id for key in omit}}
            and relation.target_id in {entity.id for entity in entities.values() if entity.id not in {entities[key].id for key in omit}}
        ),
    )


def _codes(result):
    return {issue.code for issue in result.issues}


def test_empty_requirement_scope_fails_and_empty_ratios_are_not_passes():
    graph = ModelGraph("p1", ())

    result = evaluate_strict_closure(graph)
    matrix = build_requirement_coverage(graph)
    p_gate = rflp_gate(graph)

    assert result.passed is False
    assert "empty_requirement_scope" in _codes(result)
    assert matrix.metrics["r_to_f_coverage"] == 0.0
    assert p_gate.passed is False


def test_candidate_requirement_cannot_be_closure_scope():
    result = evaluate_strict_closure(_graph(requirement_status=EntityStatus.CANDIDATE))

    assert result.passed is False
    assert {"no_accepted_requirements", "requirement_not_accepted"} <= _codes(result)


def test_each_missing_trace_stage_is_reported():
    for missing, expected in (
        (("function",), "missing_function"),
        (("logical",), "missing_logical"),
        (("physical",), "missing_physical"),
        (("verification",), "missing_verification"),
        (("validation",), "missing_validation"),
    ):
        result = evaluate_strict_closure(_graph(omit=missing))
        assert result.passed is False
        assert expected in _codes(result)


def test_placeholder_and_human_review_are_hard_closure_failures():
    placeholder = evaluate_strict_closure(
        _graph(requirement_payload={"fallback_placeholder": True})
    )
    human_review = evaluate_strict_closure(
        _graph(requirement_payload={"requires_human_review": True})
    )

    assert "fallback_placeholder" in _codes(placeholder)
    assert "requires_human_review" in _codes(human_review)


def test_open_issue_blocks_global_gate_and_closure():
    graph = _graph()
    result = evaluate_strict_closure(
        graph,
        issue_records=({"id": "issue-1", "status": "open", "severity": "P1"},),
    )

    assert result.passed is False
    assert "open_issue" in _codes(result)
    assert global_gate(graph).passed is True


def test_complete_accepted_graph_passes_strict_closure_and_global_gate():
    graph = _graph()

    result = evaluate_strict_closure(graph)

    assert result.passed is True
    assert result.requirement_ids
    assert global_gate(graph).passed is True

