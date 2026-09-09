import pytest

from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.errors import MethodologyValidationError
from rflp_lite.domain.model import ModelGraph, Patch, Relate
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.contracts import ContextBundle, StepStatus, TaskExecutionResponse
from rflp_lite.methodology.tasks import task_catalog
from rflp_lite.methodology.validation import ValidationContext
from rflp_lite.methodology.validators.reference import validate


def _context(graph, patch):
    task = next(item for item in task_catalog() if item.id == "function_identification")
    return ValidationContext("p1", task, graph, ContextBundle("p1", task.id, graph.revision, graph.entities), TaskExecutionResponse(StepStatus.COMPLETED, patch))


def test_dangling_relation_is_rejected():
    graph = ModelGraph("p1")
    patch = Patch.create("p1", "function_identification", (Relate("requirement-missing", RelationPredicate.SATISFIED_BY, "function-missing"),), "dangling", 0)

    with pytest.raises(MethodologyValidationError, match="reference_missing"):
        validate(_context(graph, patch))


def test_wrong_endpoint_kind_is_rejected():
    requirement = make_entity(EntityKind.REQUIREMENT, "需要配送", {"obligation": "支持配送"})
    function = make_entity(EntityKind.FUNCTION, "支持配送")
    graph = ModelGraph("p1", (requirement, function))
    patch = Patch.create("p1", "function_identification", (Relate(function.id, RelationPredicate.ALLOCATED_TO, requirement.id),), "wrong endpoint", 0)

    with pytest.raises(MethodologyValidationError, match="relation_endpoint_invalid"):
        validate(_context(graph, patch))
