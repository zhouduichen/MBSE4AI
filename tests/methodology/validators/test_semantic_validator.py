import pytest

from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.errors import MethodologyValidationError
from rflp_lite.domain.model import AddEntity, ModelGraph, Patch
from rflp_lite.methodology.contracts import ContextBundle, StepStatus, TaskExecutionResponse
from rflp_lite.methodology.tasks import task_catalog
from rflp_lite.methodology.validation import ValidationContext
from rflp_lite.methodology.validators.semantic import validate


def _check(task_id, entity):
    task = next(item for item in task_catalog() if item.id == task_id)
    patch = Patch.create("p1", task.id, (AddEntity(entity),), "semantic", 0)
    response = TaskExecutionResponse(StepStatus.COMPLETED, patch)
    validate(ValidationContext("p1", task, ModelGraph("p1"), ContextBundle("p1", task.id, 0, ()), response))


def test_verification_case_requires_method_and_pass_criteria():
    entity = make_entity(EntityKind.VERIFICATION_CASE, "验证配送", {"method": "review"})

    with pytest.raises(MethodologyValidationError, match="semantic_invalid"):
        _check("verification_validation", entity)


def test_function_name_cannot_be_hardware_specific():
    entity = make_entity(EntityKind.FUNCTION, "读取传感器")

    with pytest.raises(MethodologyValidationError, match="semantic_invalid"):
        _check("function_identification", entity)
