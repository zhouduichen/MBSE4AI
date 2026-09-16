import pytest

from rflp_lite.domain.errors import MethodologyValidationError
from rflp_lite.domain.model import ModelGraph, Patch, Relate
from rflp_lite.methodology.contracts import ContextBundle, StepStatus, TaskExecutionResponse
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.tasks import task_catalog
from rflp_lite.methodology.validation import ValidationContext
from rflp_lite.methodology.validators.schema import validate
from rflp_lite.methodology.vertical_generation import stage_task


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


def test_schema_validator_allows_large_patch_from_offline_lifecycle_batch():
    patch = Patch.create(
        "p1",
        "task",
        tuple(Relate(f"source-{index}", RelationPredicate.DERIVED_FROM, f"target-{index}") for index in range(33)),
        "offline batch",
        0,
    )
    response = TaskExecutionResponse(
        StepStatus.COMPLETED,
        patch=patch,
        diagnostics=("offline:lifecycle-runtime",),
    )

    validate(_context(response))


def test_schema_validator_allows_large_patch_from_offline_vertical_batch():
    patch = Patch.create(
        "p1",
        "task",
        tuple(Relate(f"source-{index}", RelationPredicate.DERIVED_FROM, f"target-{index}") for index in range(33)),
        "offline vertical batch",
        0,
    )
    response = TaskExecutionResponse(
        StepStatus.COMPLETED,
        patch=patch,
        diagnostics=("offline:vertical-runtime",),
    )

    validate(_context(response))


def test_schema_validator_allows_aggregate_structured_vertical_batch():
    task = stage_task("functional")
    response = TaskExecutionResponse(
        StepStatus.COMPLETED,
        patch=Patch.create(
            "p1",
            task.id,
            tuple(
                Relate(f"source-{index}", RelationPredicate.DERIVED_FROM, f"target-{index}")
                for index in range(33)
            ),
            "structured batch",
            0,
        ),
        diagnostics=("batch_count=5",),
    )

    validate(ValidationContext(
        "p1", task, ModelGraph("p1"), ContextBundle("p1", task.id, 0, ()), response
    ))


def test_schema_validator_allows_full_vertical_requirements_closure():
    task = stage_task("requirements")
    response = TaskExecutionResponse(
        StepStatus.COMPLETED,
        patch=Patch.create(
            "p1",
            task.id,
            tuple(
                Relate(f"source-{index}", RelationPredicate.DERIVED_FROM, f"target-{index}")
                for index in range(33)
            ),
            "requirements closure",
            0,
        ),
    )

    validate(ValidationContext(
        "p1", task, ModelGraph("p1"), ContextBundle("p1", task.id, 0, ()), response
    ))


def test_schema_validator_keeps_large_patch_limit_for_other_runtimes():
    patch = Patch.create(
        "p1",
        "task",
        tuple(Relate(f"source-{index}", RelationPredicate.DERIVED_FROM, f"target-{index}") for index in range(33)),
        "external batch",
        0,
    )
    response = TaskExecutionResponse(StepStatus.COMPLETED, patch=patch)

    with pytest.raises(MethodologyValidationError, match="32-operation"):
        validate(_context(response))
