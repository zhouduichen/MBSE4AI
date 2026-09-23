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


def _system_budget_graph(
    *,
    powers=(80, 30),
    requirement_payload=None,
) -> ModelGraph:
    payload = requirement_payload or {
        "level": "system",
        "constraints": {"max_power_w": 100},
    }
    requirement = make_entity(EntityKind.REQUIREMENT, "系统功耗预算", payload)
    functions = tuple(
        make_entity(EntityKind.FUNCTION, name, status=EntityStatus.VALIDATED)
        for name in ("采集", "执行")
    )
    logicals = tuple(
        make_entity(EntityKind.LOGICAL_COMPONENT, name, status=EntityStatus.VALIDATED)
        for name in ("采集控制器", "执行控制器")
    )
    physicals = tuple(
        make_entity(
            EntityKind.PHYSICAL_BLOCK,
            name,
            {
                "power_w": power,
                "mass_kg": 1,
                "memory_mb": 100,
                "bandwidth_mbps": 10,
                "cost": 100,
                "endurance_h": 10,
            },
            status=EntityStatus.VALIDATED,
        )
        for name, power in zip(("采集平台", "执行平台"), powers)
    )
    relations = []
    for function, logical, physical in zip(functions, logicals, physicals):
        relations.extend((
            Relation(
                f"{function.id}-requirement",
                requirement.id,
                RelationPredicate.SATISFIED_BY,
                function.id,
            ),
            Relation(
                f"{function.id}-logical",
                function.id,
                RelationPredicate.ALLOCATED_TO,
                logical.id,
            ),
            Relation(
                f"{logical.id}-physical",
                logical.id,
                RelationPredicate.ALLOCATED_TO,
                physical.id,
            ),
        ))
    return ModelGraph(
        "robot",
        (requirement, *functions, *logicals, *physicals),
        tuple(relations),
        revision=3,
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


def test_system_budget_sums_all_physical_blocks_in_requirement_scope():
    graph = _system_budget_graph()

    result = synthesize_architecture(graph)

    assert len(result.system_budgets) == 1
    budget = result.system_budgets[0]
    assert budget.status == "infeasible"
    assert budget.physical_ids == tuple(sorted(
        item.id for item in graph.entities if item.kind is EntityKind.PHYSICAL_BLOCK
    ))
    assert budget.fields["power_w"]["total"] == 110.0
    assert budget.fields["power_w"]["value_count"] == 2
    assert budget.conflicts[0] == {
        "requirement_id": budget.requirement_id,
        "physical_ids": list(budget.physical_ids),
        "field": "power_w",
        "operator": "max",
        "limit": 100.0,
        "value": 110.0,
        "scope": "system",
    }
    assert all(
        budget.as_dict() in row.as_dict()["system_budgets"]
        for row in result.physical_rows
    )
    assert all(
        set(budget.physical_ids) <= set(option["impact_entity_ids"])
        and budget.requirement_id in option["impact_entity_ids"]
        for option in budget.resolution_options
    )


def test_system_budget_distinguishes_unknown_measurement_from_conflict():
    graph = _system_budget_graph(powers=(80, "待测量"))

    budget = synthesize_architecture(graph).system_budgets[0]

    assert budget.status == "needs_measurement"
    assert budget.conflicts == ()
    assert budget.missing_fields == ("power_w",)


def test_technical_requirement_stays_per_candidate_unless_scope_is_explicitly_system():
    technical = _system_budget_graph(
        powers=(80, 30),
        requirement_payload={
            "level": "technical",
            "constraints": {"max_power_w": 50},
        },
    )
    forced_system = _system_budget_graph(
        powers=(80, 30),
        requirement_payload={
            "level": "technical",
            "constraint_scope": "system",
            "constraints": {"max_power_w": 100},
        },
    )
    component_override = _system_budget_graph(
        powers=(80, 30),
        requirement_payload={
            "level": "system",
            "constraint_scope": "component",
            "constraints": {"max_power_w": 50},
        },
    )

    technical_result = synthesize_architecture(technical)
    forced_result = synthesize_architecture(forced_system)
    component_result = synthesize_architecture(component_override)

    assert technical_result.system_budgets == ()
    assert sum(bool(row.conflicts) for row in technical_result.physical_rows) == 1
    assert len(forced_result.system_budgets) == 1
    assert forced_result.system_budgets[0].status == "infeasible"
    assert component_result.system_budgets == ()
    assert sum(bool(row.conflicts) for row in component_result.physical_rows) == 1
