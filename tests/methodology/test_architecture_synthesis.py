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
            Relation("l-p", logical.id, RelationPredicate.ALLOCATED_TO, physical.id),
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


def test_functional_flow_alone_remains_a_cross_component_boundary():
    first = make_entity(
        EntityKind.FUNCTION,
        "采集",
        status=EntityStatus.VALIDATED,
    )
    second = make_entity(
        EntityKind.FUNCTION,
        "调度",
        status=EntityStatus.VALIDATED,
    )
    third = make_entity(
        EntityKind.FUNCTION,
        "告警",
        status=EntityStatus.VALIDATED,
    )
    flow = make_entity(
        EntityKind.FUNCTIONAL_FLOW,
        "任务流",
        {
            "source_function_ids": [first.id],
            "target_function_ids": [second.id, third.id],
        },
        status=EntityStatus.VALIDATED,
    )
    graph = ModelGraph(
        "robot",
        (first, second, third, flow),
        (
            Relation("first-flow", first.id, RelationPredicate.EXCHANGES_WITH, flow.id),
            Relation("second-flow", second.id, RelationPredicate.EXCHANGES_WITH, flow.id),
            Relation("third-flow", third.id, RelationPredicate.EXCHANGES_WITH, flow.id),
        ),
    )

    result = synthesize_architecture(graph)
    dependency = next(
        item for item in result.logical_candidates
        if item.alternative == "dependency_cluster_search"
    )

    assert dependency.partitions == tuple(
        (item.id,)
        for item in sorted((first, second, third), key=lambda item: item.id)
    )
    assert dependency.cross_component_exchange_count == 1
    assert dependency.dependency_cut_count == 0


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
    assert row.logical_ids == (
        next(item.id for item in graph.entities if item.kind is EntityKind.LOGICAL_COMPONENT),
    )
    assert set(row.function_ids) == {
        item.id for item in graph.entities if item.kind is EntityKind.FUNCTION
        and item.meta.name in {"采集", "调度"}
    }
    assert {item["option"] for item in row.resolution_options} == {
        "降低计算或功耗需求",
        "更换物理候选或计算架构",
        "调整需求约束或资源预算",
        "增加电池质量或资源预算",
    }
    assert all(
        row.physical_id in item["impact_entity_ids"]
        and row.requirement_ids[0] in item["impact_entity_ids"]
        and item["reentry_stage"]
        for item in row.resolution_options
    )


def test_measurement_pending_values_do_not_count_as_feasible():
    graph = _architecture_graph()
    physical = next(
        item for item in graph.entities if item.kind is EntityKind.PHYSICAL_BLOCK
    )
    measured_payload = {
        **physical.payload,
        "power_w": 40,
        "mass_kg": 1,
        "compute": "待基准测试",
        "memory_mb": 512,
        "latency_ms": 10,
        "bandwidth_mbps": 100,
        "cost": 100,
        "thermal": "待热设计评估",
        "reliability": "待可靠性试验",
        "availability": "待运行数据确认",
        "endurance_h": 10,
    }
    edited = physical.__class__(physical.meta, measured_payload)
    graph = ModelGraph(
        graph.project_id,
        tuple(edited if item.id == physical.id else item for item in graph.entities),
        graph.relations,
        graph.revision,
    )

    row = synthesize_architecture(graph).physical_rows[0]

    assert row.status == "needs_measurement"
    assert set(row.missing_fields) >= {
        "compute", "thermal", "reliability", "availability",
    }
    assert MethodologyEngine().analyze(graph).metrics["physical_feasibility"] == "needs_measurement"


def test_methodology_report_exposes_synthesis_and_decision_evidence():
    report = MethodologyEngine().analyze(_architecture_graph())

    synthesis = report.metrics["architecture_synthesis"]
    assert synthesis["logical"]["candidate_count"] == 4
    assert synthesis["physical"]["rows"][0]["status"] == "infeasible"
    assert any(item["step"] == "logical_architecture_trade_study" for item in report.decisions)
    assert any(item["step"] == "physical_feasibility_trade_study" for item in report.decisions)
