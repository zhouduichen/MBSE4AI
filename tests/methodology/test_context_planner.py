from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.context_planner import ContextPlanner
from rflp_lite.methodology.contracts import Phase
from rflp_lite.methodology.tasks import tasks_for_phase


def test_context_planner_never_returns_relation_with_dangling_endpoint():
    task = tasks_for_phase(Phase.FUNCTIONAL)[0]
    function = make_entity(EntityKind.FUNCTION, "配送")
    requirement = make_entity(EntityKind.REQUIREMENT, "支持配送", {"obligation": "支持配送"})
    graph = ModelGraph("p1", (function, requirement), (Relation("r1", requirement.id, RelationPredicate.SATISFIED_BY, function.id),))

    planned = ContextPlanner().plan(graph, task, root_entity_ids=(requirement.id,), token_budget=10000)
    selected = {entity.id for entity in planned.entities}

    assert all(relation.source_id in selected and relation.target_id in selected for relation in planned.relations)


def test_context_planner_preserves_p0_when_budget_is_too_small():
    task = tasks_for_phase(Phase.FUNCTIONAL)[0]
    root = make_entity(EntityKind.REQUIREMENT, "很长的需求", {"obligation": "系统应在复杂环境下持续支持配送"})
    other = make_entity(EntityKind.FUNCTION, "配送")
    graph = ModelGraph("p1", (root, other))

    planned = ContextPlanner().plan(graph, task, root_entity_ids=(root.id,), token_budget=1)

    assert [entity.id for entity in planned.entities] == [root.id]


def test_context_plan_is_stably_sorted():
    task = tasks_for_phase(Phase.FUNCTIONAL)[0]
    entities = (make_entity(EntityKind.FUNCTION, "B"), make_entity(EntityKind.REQUIREMENT, "A"))
    graph = ModelGraph("p1", entities)

    first = ContextPlanner().plan(graph, task)
    second = ContextPlanner().plan(graph, task)

    assert first == second
