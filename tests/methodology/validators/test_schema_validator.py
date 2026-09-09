import pytest

from rflp_lite.domain.errors import MethodologyValidationError
from rflp_lite.domain.model import ModelGraph, Patch
from rflp_lite.methodology.contracts import ContextBundle, StepStatus, TaskExecutionResponse
from rflp_lite.methodology.tasks import task_catalog
from rflp_lite.methodology.validation import ValidationContext
from rflp_lite.methodology.validators.schema import validate


def _context(response):
    task = task_catalog()[0]
    return ValidationContext("p1", task, ModelGraph("p1"), ContextBundle("p1", task.id, 0, ()), response)


def test_schema_validator_accepts_patch_response():
    response = TaskExecutionResponse(StepStatus.COMPLETED, Patch.create("p1", "task", (), "none", 0))
    validate(_context(response))


def test_schema_validator_rejects_non_patch_response():
    response = TaskExecutionResponse(StepStatus.COMPLETED, patch="not-a-patch")

    with pytest.raises(MethodologyValidationError, match="schema_invalid"):
        validate(_context(response))
