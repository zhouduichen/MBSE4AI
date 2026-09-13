from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.architecture_synthesis import synthesize_architecture
from rflp_lite.methodology.engine import MethodologyEngine


def _architecture_graph() -> ModelGraph:
    first = make_entity(
        EntityKind.FUNCTION,
        "采集",
        {"shared_state": ["任务状态"], "dependencies": []},
        status=EntityStatus.VALIDATED,
    )
    second = make_entity(
        EntityKind.FUNCTION,
        "调度",
        {"shared_state": ["任务状态"], "dependencies": [first.id]},
        status=EntityStatus.VALIDATED,
    )
    third = make_entity(EntityKind.FUNCTION, "告警", {}, status=EntityStatus.VALIDATED)
    flow = make_entity(
        EntityKind.FUNCTIONAL_FLOW,
        "任务流",
        {"source_function_ids": [first.id], "target_function_ids": [second.id]},
    )
    logical = make_entity(EntityKind.LOGICAL_COMPONENT, "任务控制器")
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "功耗约束",
        {"constraints": {"max_power_w": 50}},
    )
    physical = make_entity(
        EntityKind.PHYSICAL_BLOCK,
        "计算平台",
        {"power_w": 80},
    )
    return ModelGraph(
        "robot",
        (first, second, third, flow, logical, requirement, physical),
        (
            Relation("f1-flow", first.id, RelationPredicate.EXCHANGES_WITH, flow.id),
            Relation("f2-flow", second.id, RelationPredicate.EXCHANGES_WITH, flow.id),
            Relation("f1-l", first.id, RelationPredicate.ALLOCATED_TO, logical.id),
            Relation("f2-l", second.id, RelationPredicate.ALLOCATED_TO, logical.id),
            Relation("r-p", requirement.id, RelationPredicate.SATISFIED_BY, physical.id),
        ),
        revision=2,
    )


def test_logical_synthesis_uses_shared_state_and_flow_to_cluster_functions():
    graph = _architecture_graph()

    result = synthesize_architecture(graph)
    dependency = next(
        item for item in result.logical_candidates
        if item.alternative == "dependency_cluster_search"
    )

    clustered = {
        frozenset(partition)
        for partition in dependency.partitions
    }
    assert clustered == {
        frozenset(
            function.id for function in graph.entities
            if function.meta.name in {"采集", "调度"}
        ),
        frozenset(
            {next(item.id for item in graph.entities if item.meta.name == "告警")}
        ),
    }
    assert dependency.shared_state_cut_count == 0
    assert dependency.cross_component_exchange_count == 0
    assert dependency.score > next(
        item.score for item in result.logical_candidates
        if item.alternative == "one_component_per_function"
    )


def test_physical_synthesis_produces_propagated_constraint_evidence():
    graph = _architecture_graph()

    result = synthesize_architecture(graph)
    row = result.physical_rows[0]

    assert row.requirement_ids == (
        next(item.id for item in graph.entities if item.kind is EntityKind.REQUIREMENT),
    )
    assert row.propagated_constraints == {"power_w": 50.0}
    assert row.status == "infeasible"
    assert row.conflicts[0]["field"] == "power_w"


def test_methodology_report_exposes_synthesis_and_decision_evidence():
    report = MethodologyEngine().analyze(_architecture_graph())

    synthesis = report.metrics["architecture_synthesis"]
    assert synthesis["logical"]["candidate_count"] == 4
    assert synthesis["physical"]["rows"][0]["status"] == "infeasible"
    assert any(item["step"] == "logical_architecture_trade_study" for item in report.decisions)
    assert any(item["step"] == "physical_feasibility_trade_study" for item in report.decisions)
