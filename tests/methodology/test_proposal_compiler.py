import pytest

from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.domain.model import AddEntity, Patch
from rflp_lite.methodology.contracts import ContextBundle, TaskExecutionRequest
from rflp_lite.methodology.proposal_compiler import compile_task_proposal, proposal_schema
from rflp_lite.methodology.tasks import output_contract, task_catalog


def _request(output_kind: EntityKind = EntityKind.REQUIREMENT) -> TaskExecutionRequest:
    task = next(item for item in task_catalog() if output_kind in item.output_kinds)
    contract = output_contract(task)
    context = ContextBundle(
        "p1",
        task.id,
        3,
        (make_entity(EntityKind.SYSTEM, "系统"),),
    )
    return TaskExecutionRequest(
        task.id,
        "v2.1",
        context,
        (),
        contract,
        100,
        patch_policy=task.patch_policy,
    )


def _proposal(**overrides):
    payload = {
        "entities": [{
            "ref": "e1",
            "kind": "requirement",
            "name": "系统应完成投递",
            "payload": {"obligation": "shall"},
            "confidence": 0.9,
            "source_ids": [],
            "evidence_ids": [],
            "lifecycle_ids": [],
        }],
        "relations": [],
        "updates": [],
        "deprecations": [],
        "reason": "提取需求",
    }
    payload.update(overrides)
    return payload


def test_proposal_schema_requires_semantic_fields_without_patch_operations():
    schema = proposal_schema(
        [EntityKind.REQUIREMENT],
        "requirements.v2",
        {},
        _request().patch_policy,
    )
    assert schema["required"] == ["entities", "relations", "updates", "deprecations", "reason"]
    assert "operations" not in schema["properties"]
    assert "op" not in schema["properties"]["entities"]["items"]["properties"]


def test_proposal_compiles_without_model_owned_patch_fields():
    request = _request()
    patch = compile_task_proposal(request, _proposal())

    assert patch is not None
    assert isinstance(patch, Patch)
    assert patch.project_id == request.context_bundle.project_id
    assert patch.expected_revision == request.context_bundle.revision
    assert isinstance(patch.operations[0], AddEntity)
    assert patch.operations[0].entity.meta.producer is Producer.LLM
    assert patch.operations[0].entity.meta.status is EntityStatus.CANDIDATE


def test_old_patch_envelope_is_not_a_task_proposal():
    with pytest.raises(ContractViolation, match="proposal.*operations"):
        compile_task_proposal(_request(), {"operations": [{"op": "ADD", "kind": "requirement"}]})


def test_missing_kind_is_rejected_at_proposal_schema_boundary():
    payload = _proposal()
    del payload["entities"][0]["kind"]
    with pytest.raises(ContractViolation, match="schema"):
        compile_task_proposal(_request(), payload)


def test_unknown_proposal_ref_is_rejected_before_patch_creation():
    payload = _proposal(entities=[])
    payload["relations"] = [{
        "source_ref": "missing",
        "predicate": "satisfiedBy",
        "target_ref": "missing-too",
        "evidence_ids": [],
    }]
    with pytest.raises(ContractViolation, match="reference"):
        compile_task_proposal(_request(), payload)

