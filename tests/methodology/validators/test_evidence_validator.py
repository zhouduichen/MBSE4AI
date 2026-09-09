import pytest

from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.errors import MethodologyValidationError
from rflp_lite.domain.model import AddEntity, ModelGraph, Patch
from rflp_lite.methodology.contracts import ContextBundle, StepStatus, TaskExecutionResponse
from rflp_lite.methodology.tasks import task_catalog
from rflp_lite.methodology.validation import ValidationContext
from rflp_lite.methodology.validators.evidence import validate


def test_forged_evidence_id_is_rejected():
    task = next(item for item in task_catalog() if item.id == "physical_candidates")
    entity = make_entity(EntityKind.PHYSICAL_BLOCK, "候选电源", {"candidate_type": "battery"}, evidence_ids=("evidence-forged",))
    graph = ModelGraph("p1")
    context = ContextBundle("p1", task.id, 0, (), evidence=())
    response = TaskExecutionResponse(StepStatus.COMPLETED, Patch.create("p1", task.id, (AddEntity(entity),), "fake evidence", 0))

    with pytest.raises(MethodologyValidationError, match="evidence_missing"):
        validate(ValidationContext("p1", task, graph, context, response))
