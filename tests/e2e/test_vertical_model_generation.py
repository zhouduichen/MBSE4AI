from pathlib import Path

from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.model import AddEntity, Patch, Relation, UpdateEntity
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.application.sysml_v2 import graph_to_sysml, sysml_to_graph
from rflp_lite.runtime.rule_based import VerticalRuleRuntime


def test_partial_operational_model_derives_requirement_and_completes_vertical_chain(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("warehouse")
    activity = make_entity(
        EntityKind.ACTIVITY,
        "监测并告警活动",
        {
            "steps": ["采集温度", "判断阈值", "发送告警"],
            "goal": "监测仓储温度并在超限时告警",
        },
    )
    graph = services.model("warehouse").graph("warehouse")
    services.model("warehouse").apply_patch(
        "warehouse",
        Patch.create(
            "warehouse",
            "import.partial-model",
            (AddEntity(activity),),
            "导入部分运行模型",
            graph.revision,
        ),
        graph.revision,
    )

    result = services.generation("warehouse").generate("warehouse")
    graph = services.model("warehouse").graph("warehouse")

    requirement = next(item for item in graph.entities if item.kind is EntityKind.REQUIREMENT)
    assert requirement.payload["derived_from_kind"] == EntityKind.ACTIVITY.value
    assert requirement.payload["source_context_ids"] == [activity.id]
    assert any(
        relation.source_id == requirement.id
        and relation.predicate is RelationPredicate.DERIVED_FROM
        and relation.target_id == activity.id
        for relation in graph.relations
    )
    assert result.traceability.complete_count == 1


def test_partial_architecture_model_reuses_existing_function_logical_and_physical_chain(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("warehouse")
    function = make_entity(
        EntityKind.FUNCTION,
        "已有温度告警功能",
        {"behavior": "监测仓储温度并在超限时告警"},
        status=EntityStatus.ACCEPTED,
        producer=Producer.IMPORT,
    )
    logical = make_entity(
        EntityKind.LOGICAL_COMPONENT,
        "已有温度告警逻辑",
        {"responsibility": "监测仓储温度并在超限时告警"},
        status=EntityStatus.ACCEPTED,
        producer=Producer.IMPORT,
    )
    physical = make_entity(
        EntityKind.PHYSICAL_BLOCK,
        "已有温度告警平台",
        {"solution_class": "领域适配执行平台"},
        status=EntityStatus.ACCEPTED,
        producer=Producer.IMPORT,
    )
    graph = services.model("warehouse").graph("warehouse")
    services.model("warehouse").apply_patch(
        "warehouse",
        Patch.create(
            "warehouse",
            "import.partial-architecture",
            (
                AddEntity(function),
                AddEntity(logical),
                AddEntity(physical),
                Relation("function-logical", function.id, RelationPredicate.ALLOCATED_TO, logical.id),
                Relation("logical-physical", logical.id, RelationPredicate.ALLOCATED_TO, physical.id),
            ),
            "导入部分架构模型",
            graph.revision,
        ),
        graph.revision,
    )

    result = services.generation("warehouse").generate("warehouse")
    graph = services.model("warehouse").graph("warehouse")

    assert result.traceability.complete_count == 1
    assert sum(item.kind is EntityKind.FUNCTION for item in graph.entities) == 1
    assert sum(item.kind is EntityKind.LOGICAL_COMPONENT for item in graph.entities) == 1
    assert sum(item.kind is EntityKind.PHYSICAL_BLOCK for item in graph.entities) == 1
    requirement = next(item for item in graph.entities if item.kind is EntityKind.REQUIREMENT)
    assert any(
        relation.source_id == requirement.id
        and relation.predicate is RelationPredicate.SATISFIED_BY
        and relation.target_id == function.id
        for relation in graph.relations
    )


def test_natural_language_generation_is_editable_and_traceable(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot", "校园无人配送机器人")

    result = services.generation("robot").generate(
        "robot", requirement_text="系统应在校园内完成配送并支持人工接管"
    )
    graph = services.model("robot").graph("robot")

    assert result.status == "completed"
    assert result.traceability.complete_count == 1
    assert all(stage.attempts == 1 for stage in result.stage_results)
    assert result.methodology.metrics["operational_context_coverage"] == 1.0
    assert result.methodology.metrics["functional_requirement_coverage"] == 1.0
    assert result.methodology.metrics["functional_flow_coverage"] == 1.0
    assert result.methodology.metrics["functional_scenario_coverage"] == 1.0
    assert result.methodology.metrics["functional_decomposition_coverage"] == 1.0
    assert result.methodology.metrics["logical_allocation_coverage"] == 1.0
    assert result.methodology.metrics["verification_coverage"] == 1.0
    assert result.methodology.metrics["validation_coverage"] == 1.0
    assert result.methodology.metrics["structured_verification_coverage"] == 1.0
    assert result.methodology.metrics["structured_validation_coverage"] == 1.0
    assert result.methodology.metrics["verification_evidence_coverage"] == 0.0
    assert result.methodology.metrics["activity_branch_coverage"] == 1.0
    assert result.methodology.metrics["physical_feasibility"] == "needs_measurement"
    assert any(
        finding.code == "physical_measurement_required"
        for finding in result.methodology.findings
    )
    assert {
        EntityKind.CONCERN,
        EntityKind.LIFECYCLE_TRANSITION,
        EntityKind.STATE,
        EntityKind.HAZARD,
        EntityKind.FAILURE_MODE,
        EntityKind.FUNCTION,
        EntityKind.LOGICAL_COMPONENT,
        EntityKind.PHYSICAL_BLOCK,
    } <= {
        entity.kind for entity in graph.entities
    }
    transitions = [
        entity for entity in graph.entities
        if entity.kind is EntityKind.LIFECYCLE_TRANSITION
    ]
    assert len(transitions) == 3
    assert {(item.payload["from_stage"], item.payload["to_stage"]) for item in transitions} == {
        ("设计", "部署"), ("部署", "运行"), ("运行", "维护"),
    }
    assert graph.revision >= 6
    assert all("候选" not in entity.meta.name and "待确认" not in entity.meta.name for entity in graph.entities)

    exported = graph_to_sysml(graph)
    assert "state def" in exported
    restored = sysml_to_graph(exported, "robot")
    assert {item.id for item in restored.entities} == {item.id for item in graph.entities}
    assert {(item.source_id, item.predicate, item.target_id) for item in restored.relations} == {
        (item.source_id, item.predicate, item.target_id) for item in graph.relations
    }

    function = next(item for item in graph.entities if item.kind is EntityKind.FUNCTION)
    services.model("robot").apply_patch(
        "robot",
        Patch.create(
            "robot",
            "review.edit",
            (UpdateEntity(function.id, {"payload": {"review_note": "人工可继续编辑"}}),),
            "验收编辑模型",
            graph.revision,
        ),
        graph.revision,
    )
    edited = services.model("robot").graph("robot")
    assert edited.entity_index[function.id].payload["review_note"] == "人工可继续编辑"
    assert "人工可继续编辑" in graph_to_sysml(edited)


def test_offline_generation_keeps_the_model_subject_from_input(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("warehouse")

    result = services.generation("warehouse").generate(
        "warehouse", requirement_text="系统应监测仓储温度并在超限时告警"
    )
    graph = services.model("warehouse").graph("warehouse")

    assert result.traceability.complete_count == 1
    system = next(item for item in graph.entities if item.kind is EntityKind.SYSTEM)
    logical = next(item for item in graph.entities if item.kind is EntityKind.LOGICAL_COMPONENT)
    physical = next(item for item in graph.entities if item.kind is EntityKind.PHYSICAL_BLOCK)
    assert system.payload["mission"] == "完成监测仓储温度"
    assert "监测仓储温度" in logical.meta.name
    assert "监测仓储温度" in physical.meta.name
    assert all("配送" not in item.meta.name for item in graph.entities)


def test_multiple_natural_language_requirements_get_separate_function_paths(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")

    result = services.generation("robot").generate(
        "robot", requirement_text="系统应自主配送；系统应支持人工接管；系统应在断网后安全运行"
    )
    graph = services.model("robot").graph("robot")

    requirements = [item for item in graph.entities if item.kind is EntityKind.REQUIREMENT]
    functions = [item for item in graph.entities if item.kind is EntityKind.FUNCTION]
    assert len(requirements) == 3
    assert len(functions) == 3
    assert result.traceability.complete_count == 3


def test_multiple_requirements_derive_separate_logical_and_physical_architecture(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")

    result = services.generation("robot").generate(
        "robot", requirement_text="系统应自主配送；系统应支持人工接管；系统应在断网后安全运行"
    )
    graph = services.model("robot").graph("robot")
    functions = [item for item in graph.entities if item.kind is EntityKind.FUNCTION]
    logicals = [item for item in graph.entities if item.kind is EntityKind.LOGICAL_COMPONENT]
    physicals = [item for item in graph.entities if item.kind is EntityKind.PHYSICAL_BLOCK]

    assert len(functions) == len(logicals) == len(physicals) == 3
    assert result.traceability.complete_count == 3
    flow = next(item for item in graph.entities if item.kind is EntityKind.FUNCTIONAL_FLOW)
    assert len(flow.payload["source_function_ids"]) == 1
    assert set(flow.payload["source_function_ids"] + flow.payload["target_function_ids"]) == {
        item.id for item in functions
    }
    assert all(flow.id in item.payload["functional_flow_ids"] for item in logicals)
    assert all(flow.id in item.payload["cross_component_flow_ids"] for item in logicals)
    assert all(
        any(
            relation.source_id == function.id
            and relation.predicate is RelationPredicate.ALLOCATED_TO
            and graph.entity_index[relation.target_id].kind is EntityKind.LOGICAL_COMPONENT
            for relation in graph.relations
        )
        for function in functions
    )
    assert all(
        any(
            relation.source_id == logical.id
            and relation.predicate is RelationPredicate.ALLOCATED_TO
            and graph.entity_index[relation.target_id].kind is EntityKind.PHYSICAL_BLOCK
            for relation in graph.relations
        )
        for logical in logicals
    )
    assert result.methodology.metrics["logical_cross_component_exchange_count"] >= 1
    assert result.methodology.metrics["logical_partition_quality"] == "needs_review"
    assert any(
        item.kind == "trade_study" and item.stage == "logical"
        for item in result.controller.actions
    )


def test_physical_architecture_propagates_structured_requirement_constraints(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")
    added = services.projects.add_requirement("robot", "系统应在功耗约束内运行")
    requirement_id = added["requirement"]["id"]
    graph = services.model("robot").graph("robot")
    services.review("robot").edit_entity(
        "robot",
        requirement_id,
        payload={"constraints": {"max_power_w": 50}},
        expected_revision=graph.revision,
    )

    services.generation("robot").generate("robot")
    graph = services.model("robot").graph("robot")
    physical = next(item for item in graph.entities if item.kind is EntityKind.PHYSICAL_BLOCK)

    assert physical.payload["source_requirement_ids"] == [requirement_id]
    assert physical.payload["propagated_constraints"] == {"max_power_w": 50}
    assert physical.payload["trade_study"]["decision_status"] == "requires_review"


def test_natural_language_constraints_reach_physical_candidate(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")

    result = services.generation("robot").generate(
        "robot", requirement_text="系统功耗不超过 50 W 且续航不少于 10 h"
    )
    graph = services.model("robot").graph("robot")
    physical = next(item for item in graph.entities if item.kind is EntityKind.PHYSICAL_BLOCK)

    assert physical.payload["propagated_constraints"] == {
        "max_power_w": 50.0,
        "min_endurance_h": 10.0,
    }
    assert physical.payload["source_requirement_ids"]
    assert physical.payload["endurance_h"] is None
    assert physical.payload["propagated_constraint_provenance"]
    impact_chain = physical.payload["impact_chain"]
    assert impact_chain["physical_ids"] == [physical.id]
    assert impact_chain["requirement_ids"] == physical.payload["source_requirement_ids"]
    assert impact_chain["function_ids"] == physical.payload["source_function_ids"]
    assert impact_chain["logical_ids"] == physical.payload["source_logical_ids"]
    assert physical.payload["resolution_options"] == []

    technical = [
        item for item in graph.entities
        if item.kind is EntityKind.REQUIREMENT
        and item.payload.get("level") == "technical"
    ]
    assert len(technical) == 1
    technical_requirement = technical[0]
    assert technical_requirement.payload["constraint_fields"] == [
        "max_power_w", "min_endurance_h",
    ]
    assert technical_requirement.payload["source_requirement_ids"]
    assert technical_requirement.payload["source_physical_ids"] == [physical.id]
    assert any(
        relation.source_id == technical_requirement.id
        and relation.predicate is RelationPredicate.DERIVED_FROM
        and relation.target_id in technical_requirement.payload["source_requirement_ids"]
        for relation in graph.relations
    )
    assert any(
        relation.source_id == technical_requirement.id
        and relation.predicate is RelationPredicate.SATISFIED_BY
        and relation.target_id == physical.id
        for relation in graph.relations
    )
    assert any(
        relation.source_id == technical_requirement.id
        and relation.predicate is RelationPredicate.VERIFIED_BY
        for relation in graph.relations
    )
    assert any(
        relation.source_id == technical_requirement.id
        and relation.predicate is RelationPredicate.VALIDATED_BY
        for relation in graph.relations
    )
    verification = next(
        item for item in graph.entities
        if item.kind is EntityKind.VERIFICATION_CASE
        and technical_requirement.id in item.payload["requirement_ids"]
    )
    validation = next(
        item for item in graph.entities
        if item.kind is EntityKind.VALIDATION_CASE
        and technical_requirement.id in item.payload["requirement_ids"]
    )
    for case in (verification, validation):
        assert case.payload["function_ids"] == impact_chain["function_ids"]
        assert case.payload["logical_component_ids"] == impact_chain["logical_ids"]
        assert case.payload["physical_ids"] == [physical.id]
        assert case.payload["constraint_fields"] == ["max_power_w", "min_endurance_h"]
        assert case.payload["verification_objective"]
        assert case.payload["evidence_required"] is True
        assert case.payload["open_questions"]
    primary_requirement = next(
        item for item in graph.entities
        if item.kind is EntityKind.REQUIREMENT
        and item.payload.get("level") != "technical"
    )
    primary_verification = next(
        item for item in graph.entities
        if item.kind is EntityKind.VERIFICATION_CASE
        and item.payload["requirement_ids"] == [primary_requirement.id]
    )
    assert primary_verification.payload["function_ids"] == impact_chain["function_ids"]
    assert primary_verification.payload["logical_component_ids"] == impact_chain["logical_ids"]
    assert primary_verification.payload["physical_ids"] == [physical.id]
    assert result.traceability.end_to_end_complete_count >= 2
    assert not any(
        finding.code == "functional_requirement_uncovered"
        and technical_requirement.id in finding.entity_ids
        for finding in result.methodology.findings
    )

    restored = sysml_to_graph(graph_to_sysml(graph), "robot")
    restored_technical = restored.entity_index[technical_requirement.id]
    assert restored_technical.payload == technical_requirement.payload
