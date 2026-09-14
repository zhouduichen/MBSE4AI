from pathlib import Path

from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.model import Patch, UpdateEntity
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.application.sysml_v2 import graph_to_sysml, sysml_to_graph
from rflp_lite.runtime.rule_based import VerticalRuleRuntime


def test_natural_language_generation_is_editable_and_traceable(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot", "校园无人配送机器人")

    result = services.generation("robot").generate(
        "robot", requirement_text="系统应在校园内完成配送并支持人工接管"
    )
    graph = services.model("robot").graph("robot")

    assert result.status == "completed"
    assert result.traceability.complete_count == 1
    assert result.methodology.metrics["operational_context_coverage"] == 1.0
    assert result.methodology.metrics["functional_requirement_coverage"] == 1.0
    assert result.methodology.metrics["functional_flow_coverage"] == 1.0
    assert result.methodology.metrics["functional_scenario_coverage"] == 1.0
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
    assert result.traceability.end_to_end_complete_count >= 2
    assert not any(
        finding.code == "functional_requirement_uncovered"
        and technical_requirement.id in finding.entity_ids
        for finding in result.methodology.findings
    )

    restored = sysml_to_graph(graph_to_sysml(graph), "robot")
    restored_technical = restored.entity_index[technical_requirement.id]
    assert restored_technical.payload == technical_requirement.payload
