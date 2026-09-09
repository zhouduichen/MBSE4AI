import pytest

from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.errors import MethodologyValidationError
from rflp_lite.domain.model import AddEntity, ModelGraph, Patch
from rflp_lite.methodology.contracts import ContextBundle, StepStatus, TaskExecutionResponse
from rflp_lite.methodology.tasks import task_catalog
from rflp_lite.methodology.validation import ValidationContext
from rflp_lite.methodology.validators.patch_policy import validate


def test_task_cannot_create_non_writable_kind():
    task = next(item for item in task_catalog() if item.id == "function_identification")
    entity = make_entity(EntityKind.PHYSICAL_BLOCK, "越权物理块")
    graph = ModelGraph("p1")
    patch = Patch.create("p1", task.id, (AddEntity(entity),), "out of policy", 0)
    context = ValidationContext("p1", task, graph, ContextBundle("p1", task.id, 0, ()), TaskExecutionResponse(StepStatus.COMPLETED, patch))

    with pytest.raises(MethodologyValidationError, match="patch_policy_violation"):
        validate(context)


def test_repair_policy_can_limit_operation_count():
    from dataclasses import replace
    from rflp_lite.methodology.policy import PatchPolicy

    task = next(item for item in task_catalog() if item.id == "function_identification")
    constrained = replace(task, patch_policy=replace(task.patch_policy, max_operations=1))
    entities = tuple(make_entity(EntityKind.FUNCTION, f"功能{i}") for i in range(2))
    patch = Patch.create("p1", task.id, tuple(AddEntity(entity) for entity in entities), "too large", 0)
    context = ValidationContext("p1", constrained, ModelGraph("p1"), ContextBundle("p1", task.id, 0, ()), TaskExecutionResponse(StepStatus.COMPLETED, patch))

    with pytest.raises(MethodologyValidationError, match="patch_policy_violation"):
        validate(context)
