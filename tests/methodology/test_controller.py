from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.controller import SystemsEngineeringController
from rflp_lite.methodology.engine import MethodologyEngine


def _conflicting_graph() -> ModelGraph:
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "续航需求",
        {"obligation": "系统应持续运行", "constraints": {"max_power_w": 50}},
    )
    function = make_entity(EntityKind.FUNCTION, "执行任务", status=EntityStatus.VALIDATED)
    logical = make_entity(EntityKind.LOGICAL_COMPONENT, "任务控制器", status=EntityStatus.VALIDATED)
    physical = make_entity(
        EntityKind.PHYSICAL_BLOCK,
        "计算平台",
        {
            "mass_kg": 1,
            "power_w": 80,
            "compute": 100,
            "memory_mb": 512,
            "latency_ms": 10,
            "bandwidth_mbps": 100,
            "cost": 100,
            "thermal": "可控",
            "reliability": "已知",
            "availability": "已知",
        },
        status=EntityStatus.VALIDATED,
    )
    relations = (
        Relation("r-f", requirement.id, RelationPredicate.SATISFIED_BY, function.id),
        Relation("f-l", function.id, RelationPredicate.ALLOCATED_TO, logical.id),
        Relation("l-p", logical.id, RelationPredicate.ALLOCATED_TO, physical.id),
    )
    return ModelGraph("p1", (requirement, function, logical, physical), relations, revision=1)


def test_controller_routes_physical_conflict_to_trade_study_options():
    graph = _conflicting_graph()
    requirement = next(item for item in graph.entities if item.kind is EntityKind.REQUIREMENT)
    physical = next(item for item in graph.entities if item.kind is EntityKind.PHYSICAL_BLOCK)
    report = MethodologyEngine().analyze(graph)

    plan = SystemsEngineeringController().plan(graph, report)

    action = next(item for item in plan.actions if item.kind == "trade_study")
    assert action.task_id == "constraint_propagation"
    assert {item["option"] for item in action.options} == {
        "降低计算或功耗需求",
        "更换物理候选或计算架构",
        "调整需求约束或资源预算",
        "增加电池质量或资源预算",
    }
    assert all(item["requires_user_decision"] for item in action.options)
    assert all(
        physical.id in item["impact_entity_ids"]
        and requirement.id in item["impact_entity_ids"]
        and item["reentry_stage"]
        for item in action.options
    )


def test_controller_plan_is_read_only_until_an_action_is_executed():
    graph = _conflicting_graph()
    plan = SystemsEngineeringController().plan(graph)

    assert plan.status == "needs_action"
    assert plan.next_action is not None
    assert plan.next_action.id.startswith("controller-action-")
    assert graph.revision == 1


def test_controller_routes_unreviewed_logical_partition_to_architecture_trade_study():
    graph = _conflicting_graph()
    requirement = next(item for item in graph.entities if item.kind is EntityKind.REQUIREMENT)
    requirement = requirement.__class__(
        requirement.meta,
        {**requirement.payload, "constraints": {"max_power_w": 100}},
    )
    logical = next(item for item in graph.entities if item.kind is EntityKind.LOGICAL_COMPONENT)
    edited = logical.__class__(
        logical.meta,
        {**logical.payload, "cohesion": "unknown", "coupling": "unknown"},
    )
    graph = ModelGraph(
        graph.project_id,
        tuple(
            edited if item.id == logical.id else requirement if item.id == requirement.id else item
            for item in graph.entities
        ),
        graph.relations,
        graph.revision,
    )

    plan = SystemsEngineeringController().plan(graph)

    action = next(item for item in plan.actions if item.kind == "trade_study")
    assert action.task_id == "dependency_clustering"
    assert {item["option"] for item in action.options} >= {
        "current_dependency_partition",
        "one_component_per_function",
        "shared_coordinator",
    }
