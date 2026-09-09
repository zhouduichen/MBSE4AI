from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.context_planner import HeuristicTokenEstimator
from rflp_lite.methodology.context import ContextBuilder
from rflp_lite.methodology.contracts import Phase
from rflp_lite.methodology.tasks import tasks_for_phase


def test_heuristic_token_estimator_handles_chinese_and_english_deterministically():
    estimator = HeuristicTokenEstimator()

    assert estimator.estimate("需求 requirement") > 0
    assert estimator.estimate("需求 requirement") == estimator.estimate("需求 requirement")
    assert estimator.estimate("需求需求") > estimator.estimate("requirement")


def test_context_builder_uses_planned_relation_subset():
    task = tasks_for_phase(Phase.FUNCTIONAL)[0]
    graph = ModelGraph("p1", (make_entity(EntityKind.PHYSICAL_BLOCK, "物理"),))

    context = ContextBuilder().build(graph, task, token_budget=1)

    assert all(entity.kind is not EntityKind.PHYSICAL_BLOCK for entity in context.entities)
    assert all(relation.source_id in {entity.id for entity in context.entities} and relation.target_id in {entity.id for entity in context.entities} for relation in context.relations)
