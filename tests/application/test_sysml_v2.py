from pathlib import Path

from rflp_lite.application.sysml_v2 import graph_to_sysml, sysml_to_graph
from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate


def _complete_graph(project_id: str) -> ModelGraph:
    system = make_entity(EntityKind.SYSTEM, "校园配送系统", {"mission": "完成配送"})
    requirement = make_entity(EntityKind.REQUIREMENT, "系统应及时配送", {"statement": "系统应及时配送", "obligation": "系统应"})
    function = make_entity(EntityKind.FUNCTION, "规划配送任务", {"behavior": "生成配送计划"})
    logical = make_entity(EntityKind.LOGICAL_COMPONENT, "任务规划组件", {"responsibility": "规划"})
    physical = make_entity(EntityKind.PHYSICAL_BLOCK, "计算执行单元", {"candidate_type": "执行单元"})
    verification = make_entity(EntityKind.VERIFICATION_CASE, "验证配送时效", {"method": "test", "pass_criteria": "满足时效"})
    validation = make_entity(EntityKind.VALIDATION_CASE, "确认配送体验", {"method": "demonstration", "pass_criteria": "用户认可"})
    entities = (system, requirement, function, logical, physical, verification, validation)
    relations = (
        Relation("rel-rf", requirement.id, RelationPredicate.SATISFIED_BY, function.id),
        Relation("rel-fl", function.id, RelationPredicate.ALLOCATED_TO, logical.id),
        Relation("rel-lp", logical.id, RelationPredicate.ALLOCATED_TO, physical.id),
        Relation("rel-rv", requirement.id, RelationPredicate.VERIFIED_BY, verification.id),
        Relation("rel-rc", requirement.id, RelationPredicate.VALIDATED_BY, validation.id),
    )
    return ModelGraph(project_id, entities, relations, revision=3)


def test_sysml_subset_round_trips_entities_relations_and_payload():
    graph = _complete_graph("p1")

    text = graph_to_sysml(graph)
    restored = sysml_to_graph(text, "p1")

    assert "part def" in text
    assert "requirement def" in text
    assert "action def" in text
    assert "satisfy" in text
    assert {item.id for item in restored.entities} == {item.id for item in graph.entities}
    assert {item.kind for item in restored.entities} == {item.kind for item in graph.entities}
    assert {item.id: item.payload for item in restored.entities} == {item.id: item.payload for item in graph.entities}
    assert {(item.source_id, item.predicate, item.target_id) for item in restored.relations} == {
        (item.source_id, item.predicate, item.target_id) for item in graph.relations
    }


def test_sysml_reader_rejects_missing_relation_endpoint():
    text = """package AI4MBSE_Model {
  // @entity: {"id":"system-1","kind":"system","name":"系统","payload":{}}
  part def system_1;
  // @relation: {"id":"rel-1","source_id":"system-1","predicate":"derivedFrom","target_id":"missing","evidence_ids":[]}
}
"""

    try:
        sysml_to_graph(text, "p1")
    except ContractViolation as exc:
        assert "endpoint" in str(exc)
    else:
        raise AssertionError("missing relation endpoint must be rejected")


def test_sysml_round_trip_preserves_technical_requirement_trace_metadata():
    root = make_entity(EntityKind.REQUIREMENT, "系统功耗需求", {"statement": "功耗受限"})
    technical = make_entity(
        EntityKind.REQUIREMENT,
        "执行单元功耗技术约束",
        {
            "level": "technical",
            "type": "constraint",
            "constraints": {"max_power_w": 50},
            "source_requirement_ids": [root.id],
            "source_physical_ids": ["physical-1"],
        },
    )
    physical = make_entity(EntityKind.PHYSICAL_BLOCK, "执行单元", {"power_w": None})
    graph = ModelGraph(
        "p1",
        (root, technical, physical),
        (
            Relation("technical-root", technical.id, RelationPredicate.DERIVED_FROM, root.id),
            Relation("technical-physical", technical.id, RelationPredicate.SATISFIED_BY, physical.id),
        ),
    )

    restored = sysml_to_graph(graph_to_sysml(graph), "p1")

    restored_technical = restored.entity_index[technical.id]
    assert restored_technical.payload == technical.payload
    assert any(
        relation.source_id == technical.id
        and relation.predicate is RelationPredicate.DERIVED_FROM
        and relation.target_id == root.id
        for relation in restored.relations
    )
    assert any(
        relation.source_id == technical.id
        and relation.predicate is RelationPredicate.SATISFIED_BY
        and relation.target_id == physical.id
        for relation in restored.relations
    )


def test_pipeline_sysml_round_trip_review_edit_and_deliverables(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces")
    services.projects.create("robot")
    services.requirements_input("robot").ensure_text_requirements(
        "系统功耗不超过 50 W 且续航不少于 10 h"
    )
    services.analysis("robot").run("robot", force_new=True)
    graph = services.model("robot").graph("robot")

    imported = sysml_to_graph(graph_to_sysml(graph), "robot")

    assert {item.id: item.kind for item in imported.entities} == {
        item.id: item.kind for item in graph.entities
    }
    assert {item.id: dict(item.payload) for item in imported.entities} == {
        item.id: dict(item.payload) for item in graph.entities
    }
    assert {
        (item.source_id, item.predicate, item.target_id)
        for item in imported.relations
    } == {
        (item.source_id, item.predicate, item.target_id)
        for item in graph.relations
    }

    function = next(item for item in graph.entities if item.kind is EntityKind.FUNCTION)
    services.review("robot").edit_entity(
        "robot",
        function.id,
        payload={"review_note": "人工确认功能职责"},
    )
    edited = services.model("robot").graph("robot").entity_index[function.id]
    assert edited.payload["review_note"] == "人工确认功能职责"

    package = services.deliverables("robot").build("robot")
    model_entities = package["artifacts"]["model"]["content"]["entities"]
    assert any(
        item["kind"] == EntityKind.REQUIREMENT.value
        and item["payload"].get("level") == "technical"
        for item in model_entities
    )
    assert "技术约束" in package["artifacts"]["sysml"]["content"]
    assert package["artifacts"]["traceability"]["content"]["metrics"]
    assert package["artifacts"]["vv_plan"]["content"]["rows"]
    assert package["artifacts"]["rflp"]["content"]["edges"]
