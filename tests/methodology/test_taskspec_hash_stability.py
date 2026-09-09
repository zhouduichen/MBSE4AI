from dataclasses import replace

from rflp_lite.methodology.contracts import CompletionCondition
from rflp_lite.methodology.tasks import task_catalog, task_spec_hash


def test_task_spec_hash_changes_when_completion_condition_changes():
    task = task_catalog()[0]
    changed = replace(task, completion_condition=CompletionCondition(minimum_entities=1))

    assert task_spec_hash(task) != task_spec_hash(changed)


def test_task_spec_hash_changes_when_failure_route_changes():
    task = task_catalog()[0]
    changed = replace(task, failure_routes=())

    assert task_spec_hash(task) != task_spec_hash(changed)
