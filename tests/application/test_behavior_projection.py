from rflp_lite.application.projections.behavior import build_behavior_view
from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate


def _behavior_graph(*, explicit_requirement_links: bool = True) -> tuple[ModelGraph, str]:
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "系统应在异常时告警",
        {"statement": "系统应在异常时告警"},
    )
    use_case = make_entity(
        EntityKind.USE_CASE,
        "处理异常告警",
        {"goal": "完成异常告警处理", "requirement_ids": [requirement.id]},
    )
    scenario = make_entity(
        EntityKind.OPERATIONAL_SCENARIO,
        "异常告警运行场景",
        {"actor_ids": [], "steps": [], "branches": []},
    )
    activity = make_entity(
        EntityKind.ACTIVITY,
        "识别并发送告警",
        {
            "scenario_id": scenario.id,
            "order": 1,
            "action": "识别异常并发送告警",
            "requirement_ids": [requirement.id],
        },
    )
    relations = [
        Relation("uc-activity", use_case.id, RelationPredicate.DECOMPOSES, activity.id),
    ]
    if explicit_requirement_links:
        relations.extend(
            (
                Relation("r-uc", requirement.id, RelationPredicate.DERIVED_FROM, use_case.id),
                Relation("r-scenario", requirement.id, RelationPredicate.DERIVED_FROM, scenario.id),
                Relation("r-activity", requirement.id, RelationPredicate.DERIVED_FROM, activity.id),
            )
        )
    graph = ModelGraph(
        "p1",
        (requirement, use_case, scenario, activity),
        tuple(relations),
    )
    return graph, requirement.id


def test_behavior_projection_exposes_explicit_requirement_links() -> None:
    graph, requirement_id = _behavior_graph()

    view = build_behavior_view(graph)

    assert {row["source"] for row in view["relations"]} >= {requirement_id}
    use_case = view["use_cases"][0]
    assert use_case["requirement_ids"] == [requirement_id]
    scenario = view["scenarios"][0]
    assert scenario["requirement_ids"] == [requirement_id]
    assert view["sequence_diagrams"][0]["requirement_ids"] == [requirement_id]
    activity_diagram = view["activity_diagrams"][0]
    assert activity_diagram["format"] == "mermaid"
    assert "flowchart TD" in activity_diagram["mermaid"]
    assert activity_diagram["requirement_ids"] == [requirement_id]
    assert activity_diagram["editable_entity_ids"][-1] == next(
        item.id for item in graph.entities if item.kind is EntityKind.ACTIVITY
    )
    assert EntityKind.REQUIREMENT.value not in view["records"]


def test_behavior_projection_reads_legacy_requirement_payload_without_fabricating_relation() -> None:
    graph, requirement_id = _behavior_graph(explicit_requirement_links=False)

    view = build_behavior_view(graph)

    assert view["use_cases"][0]["requirement_ids"] == [requirement_id]
    assert not any(row["source"] == requirement_id for row in view["relations"])
