import pytest

from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.errors import MethodologyValidationError
from rflp_lite.domain.model import AddEntity, ModelGraph, Patch, UpdateEntity
from rflp_lite.methodology.contracts import ContextBundle, StepStatus, TaskExecutionResponse
from rflp_lite.methodology.tasks import task_catalog
from rflp_lite.methodology.validation import ValidationContext
from rflp_lite.methodology.validators.identity import validate


def _context(graph, patch, task_id="functional_decomposition"):
    task = next(item for item in task_catalog() if item.id == task_id)
    response = TaskExecutionResponse(StepStatus.COMPLETED, patch)
    return ValidationContext("p1", task, graph, ContextBundle("p1", task.id, graph.revision, graph.entities), response)


def test_duplicate_add_id_is_rejected():
    entity = make_entity(EntityKind.FUNCTION, "配送")
    graph = ModelGraph("p1", (entity,))
    patch = Patch.create("p1", "functional_decomposition", (AddEntity(entity),), "duplicate", graph.revision)

    with pytest.raises(MethodologyValidationError, match="identity_conflict"):
        validate(_context(graph, patch))


def test_update_missing_entity_is_rejected():
    graph = ModelGraph("p1")
    patch = Patch.create("p1", "functional_decomposition", (UpdateEntity("function-missing", {"name": "新功能"}),), "missing", 0)

    with pytest.raises(MethodologyValidationError, match="identity_conflict"):
        validate(_context(graph, patch))


@pytest.mark.parametrize("status,payload", [(EntityStatus.LOCKED, {}), (EntityStatus.CANDIDATE, {"user_modified": True})])
def test_update_locked_or_user_modified_entity_is_rejected(status, payload):
    entity = make_entity(EntityKind.FUNCTION, "配送", payload, status=status)
    graph = ModelGraph("p1", (entity,))
    patch = Patch.create("p1", "functional_decomposition", (UpdateEntity(entity.id, {"name": "修改"}),), "locked", graph.revision)

    with pytest.raises(MethodologyValidationError, match="identity_conflict"):
        validate(_context(graph, patch))


def test_system_definition_cannot_add_a_second_system():
    existing = make_entity(EntityKind.SYSTEM, "已有系统")
    another = make_entity(EntityKind.SYSTEM, "第二个系统")
    graph = ModelGraph("p1", (existing,))
    patch = Patch.create("p1", "system_definition", (AddEntity(another),), "second", graph.revision)

    with pytest.raises(MethodologyValidationError, match="identity_conflict"):
        validate(_context(graph, patch, "system_definition"))
