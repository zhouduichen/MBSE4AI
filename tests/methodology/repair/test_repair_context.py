from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.repair_context import build_repair_context


def test_repair_context_contains_roots_and_one_hop_neighbors_only():
    requirement = make_entity(EntityKind.REQUIREMENT, "需求", {"obligation": "支持配送"})
    function = make_entity(EntityKind.FUNCTION, "支持配送")
    unrelated = make_entity(EntityKind.PHYSICAL_BLOCK, "无关物理块")
    graph = ModelGraph("p1", (requirement, function, unrelated), (
        Relation("r1", requirement.id, RelationPredicate.SATISFIED_BY, function.id),
    ))

    context = build_repair_context(
        "p1", "run-1", "issue-1", {"code": "broken_requirement_function_trace", "entity_ids": [requirement.id]}, graph,
    )

    assert context.root_entity_ids == (requirement.id,)
    assert {entity.id for entity in context.local_entities} == {requirement.id, function.id}
    assert context.local_relations[0].id == "r1"
    assert unrelated.id not in {entity.id for entity in context.local_entities}
