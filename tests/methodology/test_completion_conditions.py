from dataclasses import replace

from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.completion import evaluate_completion
from rflp_lite.methodology.contracts import CompletionCondition, ContextBundle, StepStatus, TaskExecutionResponse
from rflp_lite.methodology.tasks import task_catalog


def test_completion_condition_enforces_minimum_entity_count_and_acceptance():
    base = next(item for item in task_catalog() if item.id == "function_identification")
    task = replace(base, completion_condition=CompletionCondition(frozenset({EntityKind.FUNCTION}), 1, True))
    graph = ModelGraph("p1", (make_entity(EntityKind.FUNCTION, "配送"),))

    result = evaluate_completion(task, graph, TaskExecutionResponse(StepStatus.COMPLETED))

    assert result.passed is False
    assert "completion_requires_accepted" in result.issue_codes


def test_completion_condition_can_require_a_named_trace():
    base = next(item for item in task_catalog() if item.id == "function_identification")
    task = replace(base, completion_condition=CompletionCondition(required_trace_rules=("r_to_f",)))
    requirement = make_entity(EntityKind.REQUIREMENT, "需求", {"obligation": "支持配送"}, status=EntityStatus.ACCEPTED)
    function = make_entity(EntityKind.FUNCTION, "支持配送")
    graph = ModelGraph("p1", (requirement, function), (Relation("r1", requirement.id, RelationPredicate.SATISFIED_BY, function.id),))

    result = evaluate_completion(task, graph)

    assert result.passed is True
