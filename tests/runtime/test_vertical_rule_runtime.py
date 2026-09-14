from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.model import ModelGraph, Relation, apply_patch
from rflp_lite.methodology.contracts import ContextBundle, TaskExecutionRequest
from rflp_lite.methodology.engine import MethodologyEngine
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.runtime.rule_based import _partition_functions, _partition_label
from rflp_lite.runtime.rule_based import VerticalRuleRuntime


def _requirements_request(entities, relations=(), revision=0):
    context = ContextBundle(
        "warehouse", "vertical.requirements", revision, tuple(entities), tuple(relations)
    )
    return TaskExecutionRequest(
        "vertical.requirements",
        "v2.1",
        context,
        (),
        {"output_kinds": [kind.value for kind in EntityKind]},
        3000,
    )


def test_requirements_stage_derives_one_requirement_from_existing_activity_and_is_idempotent():
    activity = make_entity(
        EntityKind.ACTIVITY,
        "监测并告警活动",
        {"goal": "监测仓储温度并在超限时告警"},
    )
    runtime = VerticalRuleRuntime()
    request = _requirements_request((activity,))

    response = runtime.execute(request)
    requirement = next(
        operation.entity
        for operation in response.patch.operations
        if hasattr(operation, "entity") and operation.entity.kind is EntityKind.REQUIREMENT
    )
    graph = apply_patch(ModelGraph("warehouse", (activity,)), response.patch)

    assert requirement.payload["statement"] == "系统应监测仓储温度并在超限时告警"
    assert requirement.payload["derived_from_kind"] == EntityKind.ACTIVITY.value
    assert requirement.payload["source_context_ids"] == [activity.id]
    assert any(
        relation.source_id == requirement.id
        and relation.predicate is RelationPredicate.DERIVED_FROM
        and relation.target_id == activity.id
        for relation in graph.relations
    )

    repeat = runtime.execute(_requirements_request(graph.entities, graph.relations, graph.revision))
    assert repeat.patch is None


def test_requirements_stage_derives_from_existing_function_context():
    function = make_entity(
        EntityKind.FUNCTION,
        "已有温度告警功能",
        {"behavior": "监测仓储温度并在超限时告警"},
    )

    response = VerticalRuleRuntime().execute(_requirements_request((function,)))
    requirement = next(
        operation.entity
        for operation in response.patch.operations
        if hasattr(operation, "entity") and operation.entity.kind is EntityKind.REQUIREMENT
    )

    assert requirement.payload["derived_from_kind"] == EntityKind.FUNCTION.value
    assert requirement.payload["source_context_ids"] == [function.id]
    assert requirement.payload["statement"] == "系统应监测仓储温度并在超限时告警"


def test_requirements_stage_reuses_semantically_matching_lifecycle_transition():
    stage = make_entity(
        EntityKind.LIFECYCLE_STAGE,
        "设计到运行",
        {"sequence": ["设计", "部署", "运行"]},
    )
    transition = make_entity(
        EntityKind.LIFECYCLE_TRANSITION,
        "部署到运行",
        {"from_stage": "部署", "to_stage": "运行", "trigger": "部署验收完成"},
    )

    response = VerticalRuleRuntime().execute(_requirements_request((stage, transition)))

    assert not any(
        hasattr(operation, "entity")
        and operation.entity.kind is EntityKind.LIFECYCLE_TRANSITION
        and operation.entity.payload.get("from_stage") == "部署"
        and operation.entity.payload.get("to_stage") == "运行"
        for operation in response.patch.operations
    )


def _logical_request(entities, relations=(), decision=None):
    context = ContextBundle(
        "robot", "vertical.logical", 3, tuple(entities), tuple(relations),
        controller_decisions=(decision,) if decision else (),
    )
    return TaskExecutionRequest(
        "vertical.logical", "v2.1", context, (),
        {"output_kinds": ["logical_component", "interface", "state"]}, 3000,
    )


def _physical_request(entities, relations=(), decision=None):
    context = ContextBundle(
        "robot", "vertical.physical", 3, tuple(entities), tuple(relations),
        controller_decisions=(decision,) if decision else (),
    )
    return TaskExecutionRequest(
        "vertical.physical", "v2.1", context, (),
        {"output_kinds": ["physical_block", "requirement"]}, 3000,
    )


def test_partition_functions_uses_explicit_key_and_falls_back_to_function_id():
    first = make_entity(EntityKind.FUNCTION, "规划", {"partition_key": "任务管理"})
    second = make_entity(EntityKind.FUNCTION, "执行", {"partition_key": "任务管理"})
    third = make_entity(EntityKind.FUNCTION, "监控", {})

    groups = _partition_functions((first, second, third))

    assert [[item.meta.name for item in group] for group in groups] == [
        ["规划", "执行"],
        ["监控"],
    ]


def test_partition_functions_groups_shared_state_and_exposes_labels():
    first = make_entity(EntityKind.FUNCTION, "采集", {"shared_state": ["任务状态"]})
    second = make_entity(EntityKind.FUNCTION, "调度", {"shared_state": ["任务状态"]})

    groups = _partition_functions((first, second))

    assert len(groups) == 1
    assert _partition_label(groups[0]) == "共享状态：任务状态"


def test_partition_functions_clusters_transitive_dependency_references():
    first = make_entity(EntityKind.FUNCTION, "采集", {})
    second = make_entity(EntityKind.FUNCTION, "分析", {"dependencies": [first.id]})
    third = make_entity(EntityKind.FUNCTION, "决策", {"depends_on": [second.meta.name]})

    groups = _partition_functions((first, second, third))

    assert [[item.meta.name for item in group] for group in groups] == [[
        "采集", "分析", "决策",
    ]]


def test_logical_component_records_dependency_evidence():
    first = make_entity(EntityKind.FUNCTION, "采集", {})
    second = make_entity(EntityKind.FUNCTION, "分析", {"dependencies": [first.id]})

    response = VerticalRuleRuntime().execute(_logical_request((first, second)))
    graph = apply_patch(ModelGraph("robot", (first, second), revision=3), response.patch)
    logical = next(item for item in graph.entities if item.kind is EntityKind.LOGICAL_COMPONENT)

    assert logical.payload["dependency_evidence"] == [first.id]
    assert "显式功能依赖" in logical.payload["partition_basis"]
    assert "dependency_cluster_search" in logical.payload["alternative_partitions"]


def test_shared_state_partition_is_reviewable_for_high_coupling():
    first = make_entity(EntityKind.FUNCTION, "采集", {"shared_state": ["任务状态"]})
    second = make_entity(EntityKind.FUNCTION, "调度", {"shared_state": ["任务状态"]})
    context = ContextBundle(
        "robot",
        "vertical.logical",
        0,
        (first, second),
    )
    request = TaskExecutionRequest(
        "vertical.logical",
        "v2.1",
        context,
        (),
        {"output_kinds": ["logical_component"]},
        100,
    )

    response = VerticalRuleRuntime().execute(request)
    graph = apply_patch(ModelGraph("robot", (first, second)), response.patch)
    logical = next(item for item in graph.entities if item.kind is EntityKind.LOGICAL_COMPONENT)
    report = MethodologyEngine().analyze(graph)

    assert logical.payload["coupling"] == "high"
    assert any(item.code == "logical_partition_needs_review" for item in report.findings)


def test_one_component_per_function_repartitions_existing_logical_components():
    first = make_entity(EntityKind.FUNCTION, "采集任务", {"shared_state": ["task_state"]})
    second = make_entity(EntityKind.FUNCTION, "执行任务", {"shared_state": ["task_state"]})
    old = make_entity(
        EntityKind.LOGICAL_COMPONENT,
        "共享任务逻辑组件",
        {"cohesion": "high", "coupling": "high"},
        status=EntityStatus.VALIDATED,
    )
    graph = ModelGraph(
        "robot",
        (first, second, old),
        (
            Relation("f1-l", first.id, RelationPredicate.ALLOCATED_TO, old.id),
            Relation("f2-l", second.id, RelationPredicate.ALLOCATED_TO, old.id),
        ),
        revision=3,
    )

    response = VerticalRuleRuntime().execute(_logical_request(
        graph.entities,
        graph.relations,
        {
            "action_id": "a1",
            "option_id": "o1",
            "option": "one_component_per_function",
            "task_id": "architecture_evaluation",
            "revision": 3,
        },
    ))
    result = apply_patch(graph, response.patch)

    active = [
        item for item in result.entities
        if item.kind is EntityKind.LOGICAL_COMPONENT
        and item.meta.status is not EntityStatus.DEPRECATED
    ]
    assert result.entity_index[old.id].meta.status is EntityStatus.DEPRECATED
    assert len(active) == 2
    assert all(item.payload["architecture_variant"] == "one_component_per_function" for item in active)
    assert all(item.payload["architecture_decision"]["option_id"] == "o1" for item in active)


def test_shared_coordinator_variant_is_marked_high_coupling():
    first = make_entity(EntityKind.FUNCTION, "采集任务", {"shared_state": ["task_state"]})
    second = make_entity(EntityKind.FUNCTION, "执行任务", {"shared_state": ["task_state"]})

    response = VerticalRuleRuntime().execute(_logical_request(
        (first, second),
        decision={
            "action_id": "a2",
            "option_id": "o2",
            "option": "shared_coordinator",
            "task_id": "architecture_evaluation",
            "revision": 0,
        },
    ))
    logical = next(
        operation.entity
        for operation in response.patch.operations
        if hasattr(operation, "entity")
        and operation.entity.kind is EntityKind.LOGICAL_COMPONENT
    )

    assert logical.payload["architecture_variant"] == "shared_coordinator"
    assert logical.payload["coupling"] == "high"
    assert logical.payload["architecture_decision"]["action_id"] == "a2"


def test_dependency_cluster_variant_applies_synthesized_partition():
    first = make_entity(EntityKind.FUNCTION, "采集", {"shared_state": ["任务状态"]})
    second = make_entity(EntityKind.FUNCTION, "调度", {"shared_state": ["任务状态"]})
    third = make_entity(EntityKind.FUNCTION, "告警")

    response = VerticalRuleRuntime().execute(_logical_request(
        (first, second, third),
        decision={
            "action_id": "a-cluster",
            "option_id": "o-cluster",
            "option": "dependency_cluster_search",
            "task_id": "architecture_evaluation",
            "revision": 0,
        },
    ))
    components = [
        operation.entity for operation in response.patch.operations
        if hasattr(operation, "entity")
        and operation.entity.kind is EntityKind.LOGICAL_COMPONENT
    ]

    assert len(components) == 2
    assert all(item.payload["architecture_variant"] == "dependency_cluster_search" for item in components)
    assert sorted(len(item.payload["dependencies"]) for item in components) == [1, 2]


def test_physical_candidate_trade_study_adds_traceable_alternative():
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "功耗需求",
        {
            "constraints": {"max_power_w": 50},
            "constraint_provenance": [{"field": "power_w"}],
        },
    )
    function = make_entity(EntityKind.FUNCTION, "执行任务")
    logical = make_entity(EntityKind.LOGICAL_COMPONENT, "任务控制器")
    physical = make_entity(
        EntityKind.PHYSICAL_BLOCK,
        "配送协同执行平台",
        {"power_w": 80},
    )
    context = ContextBundle(
        "robot",
        "vertical.physical",
        4,
        (requirement, function, logical, physical),
        (
            Relation("r-f", requirement.id, RelationPredicate.SATISFIED_BY, function.id),
            Relation("f-l", function.id, RelationPredicate.ALLOCATED_TO, logical.id),
            Relation("l-p", logical.id, RelationPredicate.ALLOCATED_TO, physical.id),
        ),
        controller_decisions=(
            {
                "action_id": "a3",
                "option_id": "o3",
                "option": "更换物理候选或计算架构",
                "task_id": "allocation_tradeoff",
                "revision": 4,
            },
        ),
    )
    request = TaskExecutionRequest(
        "vertical.physical",
        "v2.1",
        context,
        (),
        {"output_kinds": ["physical_block", "requirement"]},
        3000,
    )

    response = VerticalRuleRuntime().execute(request)
    alternative = next(
        operation.entity
        for operation in response.patch.operations
        if hasattr(operation, "entity")
        and operation.entity.kind is EntityKind.PHYSICAL_BLOCK
        and operation.entity.payload.get("candidate_variant") == "alternative"
    )

    assert alternative.payload["propagated_constraints"] == {"max_power_w": 50}
    assert alternative.payload["architecture_decision"]["option_id"] == "o3"
    assert alternative.payload["source_requirement_ids"] == [requirement.id]


def test_physical_budget_trade_does_not_fabricate_measurements():
    logical = make_entity(EntityKind.LOGICAL_COMPONENT, "任务控制器")
    physical = make_entity(
        EntityKind.PHYSICAL_BLOCK,
        "配送协同执行平台",
        {"power_w": 80, "mass_kg": 12, "propagated_constraints": {"max_power_w": 50}},
    )
    context = ContextBundle(
        "robot",
        "vertical.physical",
        4,
        (logical, physical),
        (Relation("l-p", logical.id, RelationPredicate.ALLOCATED_TO, physical.id),),
        controller_decisions=(
            {
                "action_id": "a5",
                "option_id": "o5",
                "option": "降低计算或功耗需求",
                "task_id": "constraint_propagation",
                "revision": 4,
            },
        ),
    )
    request = TaskExecutionRequest(
        "vertical.physical", "v2.1", context, (), {"output_kinds": ["physical_block"]}, 3000
    )

    response = VerticalRuleRuntime().execute(request)
    update = next(
        operation for operation in response.patch.operations
        if operation.__class__.__name__ == "UpdateEntity"
    )

    assert update.field_patch["payload"]["power_w"] == 80
    assert update.field_patch["payload"]["mass_kg"] == 12
    assert update.field_patch["payload"]["propagated_constraints"] == {"max_power_w": 50}
    assert update.field_patch["payload"]["architecture_decision"]["option_id"] == "o5"


def test_locked_physical_candidate_gets_unmeasured_alternative():
    logical = make_entity(EntityKind.LOGICAL_COMPONENT, "任务控制器")
    physical = make_entity(
        EntityKind.PHYSICAL_BLOCK,
        "配送协同执行平台",
        {"power_w": 80},
        status=EntityStatus.LOCKED,
    )
    context = ContextBundle(
        "robot",
        "vertical.physical",
        4,
        (logical, physical),
        (Relation("l-p", logical.id, RelationPredicate.ALLOCATED_TO, physical.id),),
        controller_decisions=(
            {
                "action_id": "a6",
                "option_id": "o6",
                "option": "降低计算或功耗需求",
                "task_id": "constraint_propagation",
                "revision": 4,
            },
        ),
    )
    request = TaskExecutionRequest(
        "vertical.physical", "v2.1", context, (), {"output_kinds": ["physical_block"]}, 3000
    )

    response = VerticalRuleRuntime().execute(request)
    alternative = next(
        operation.entity for operation in response.patch.operations
        if hasattr(operation, "entity")
        and operation.entity.kind is EntityKind.PHYSICAL_BLOCK
        and operation.entity.payload.get("candidate_variant") == "alternative"
    )

    assert alternative.payload["blocked_by_locked_entity"] is True
    assert alternative.payload["power_w"] is None
    assert alternative.payload["architecture_decision"]["option_id"] == "o6"


def test_locked_logical_component_is_not_deprecated_when_variant_is_generated():
    function = make_entity(EntityKind.FUNCTION, "执行任务")
    locked = make_entity(
        EntityKind.LOGICAL_COMPONENT,
        "锁定控制器",
        {},
        status=EntityStatus.LOCKED,
    )
    response = VerticalRuleRuntime().execute(_logical_request(
        (function, locked),
        (Relation("f-l", function.id, RelationPredicate.ALLOCATED_TO, locked.id),),
        {
            "action_id": "a4",
            "option_id": "o4",
            "option": "shared_coordinator",
            "task_id": "architecture_evaluation",
            "revision": 3,
        },
    ))

    assert not any(
        operation.__class__.__name__ == "Deprecate"
        and operation.entity_id == locked.id
        for operation in response.patch.operations
    )
    assert any(
        hasattr(operation, "entity")
        and operation.entity.kind is EntityKind.LOGICAL_COMPONENT
        and operation.entity.payload.get("blocked_by_locked_entity") is True
        for operation in response.patch.operations
    )


def test_physical_constraints_create_idempotent_technical_requirement():
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "任务资源约束",
        {
            "constraints": {"max_power_w": 50, "min_endurance_h": 10},
            "constraint_provenance": [{"field": "power_w", "source": "user_input"}],
        },
    )
    function = make_entity(EntityKind.FUNCTION, "执行任务")
    logical = make_entity(EntityKind.LOGICAL_COMPONENT, "任务控制器")
    relations = (
        Relation("r-f", requirement.id, RelationPredicate.SATISFIED_BY, function.id),
        Relation("f-l", function.id, RelationPredicate.ALLOCATED_TO, logical.id),
    )
    graph = ModelGraph("robot", (requirement, function, logical), relations, revision=3)

    first = VerticalRuleRuntime().execute(_physical_request(graph.entities, graph.relations))
    first_graph = apply_patch(graph, first.patch)
    technical = [
        item for item in first_graph.entities
        if item.kind is EntityKind.REQUIREMENT and item.payload.get("level") == "technical"
    ]
    second_request = _physical_request(
        first_graph.entities,
        first_graph.relations,
    )
    second = VerticalRuleRuntime().execute(second_request)

    assert len(technical) == 1
    assert technical[0].payload["constraints"] == {
        "max_power_w": 50, "min_endurance_h": 10,
    }
    assert technical[0].payload["constraint_provenance"] == [
        {"field": "power_w", "source": "user_input"},
    ]
    assert second.patch is None


def test_physical_replacement_candidate_gets_its_own_technical_requirement():
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "任务功耗约束",
        {"constraints": {"max_power_w": 50}},
    )
    function = make_entity(EntityKind.FUNCTION, "执行任务")
    logical = make_entity(EntityKind.LOGICAL_COMPONENT, "任务控制器")
    response = VerticalRuleRuntime().execute(_physical_request(
        (requirement, function, logical),
        (
            Relation("r-f", requirement.id, RelationPredicate.SATISFIED_BY, function.id),
            Relation("f-l", function.id, RelationPredicate.ALLOCATED_TO, logical.id),
        ),
        {
            "action_id": "a-physical",
            "option_id": "replace",
            "option": "更换物理候选或计算架构",
            "task_id": "allocation_tradeoff",
            "revision": 3,
        },
    ))
    physical = next(
        operation.entity for operation in response.patch.operations
        if hasattr(operation, "entity") and operation.entity.kind is EntityKind.PHYSICAL_BLOCK
    )
    technical = next(
        operation.entity for operation in response.patch.operations
        if hasattr(operation, "entity")
        and operation.entity.kind is EntityKind.REQUIREMENT
        and operation.entity.payload.get("level") == "technical"
    )

    assert physical.payload["candidate_variant"] == "alternative"
    assert technical.payload["source_physical_ids"] == [physical.id]
    assert any(
        hasattr(operation, "source_id")
        and operation.source_id == technical.id
        and operation.target_id == physical.id
        and operation.predicate is RelationPredicate.SATISFIED_BY
        for operation in response.patch.operations
    )
