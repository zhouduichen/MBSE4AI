from dataclasses import replace

import pytest

from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.domain.model import AddEntity, ModelGraph, Patch, Relate, UpdateEntity, apply_patch
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
            "local_ref": "e1",
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


def _system_payload():
    return {
        "mission": "支持校园配送服务",
        "system_boundary": {
            "inside": ["配送服务能力"],
            "outside": ["校园道路环境"],
        },
        "objectives": ["完成可追踪的配送任务"],
        "environment_assumptions": ["校园网络可用"],
        "exclusions": ["不定义具体硬件实现"],
        "open_questions": ["待确认高峰期任务量"],
    }


def _system_request(entities=(), revision=3):
    task = next(item for item in task_catalog() if item.id == "system_definition")
    context = ContextBundle("p1", task.id, revision, tuple(entities))
    return TaskExecutionRequest(
        task.id, "v2.1", context, (), output_contract(task), 4000,
        patch_policy=task.patch_policy,
    )


def _system_proposal(**overrides):
    payload = {
        "entities": [],
        "relations": [],
        "updates": [],
        "deprecations": [],
        "reason": "补全系统定义",
    }
    payload.update(overrides)
    return payload


def test_system_definition_contract_describes_system_payload_and_cardinality():
    task = next(item for item in task_catalog() if item.id == "system_definition")
    contract = output_contract(task)
    payload = contract["properties"]["entities"]["items"]["properties"]["payload"]

    assert task.completion_condition.minimum_entities == 1
    assert payload["additionalProperties"] is False
    assert set(payload["required"]) == {
        "mission", "system_boundary", "objectives",
        "environment_assumptions", "exclusions", "open_questions",
    }
    assert contract["properties"]["updates"]["items"]["properties"]["field_patch"]["properties"]["payload"] == payload


def test_system_definition_enriches_existing_system_without_adding_one():
    system = make_entity(EntityKind.SYSTEM, "系统")
    request = _system_request((system,))
    proposal = _system_proposal(updates=[{
        "entity_id": system.id,
        "field_patch": {"payload": _system_payload()},
    }])

    patch = compile_task_proposal(request, proposal)

    assert patch is not None
    assert len(patch.operations) == 1
    assert isinstance(patch.operations[0], UpdateEntity)
    next_graph = apply_patch(ModelGraph("p1", (system,), revision=3), patch)
    assert next_graph.revision == 4
    assert sum(entity.kind is EntityKind.SYSTEM for entity in next_graph.entities) == 1
    assert next_graph.entity_index[system.id].payload == _system_payload()


def test_system_definition_creates_one_system_when_context_has_none():
    request = _system_request((), revision=0)
    proposal = _system_proposal(entities=[{
        "local_ref": "new:system:1",
        "name": "校园配送系统",
        "payload": _system_payload(),
    }])

    patch = compile_task_proposal(request, proposal)

    assert patch is not None
    assert len(patch.operations) == 1
    assert isinstance(patch.operations[0], AddEntity)
    next_graph = apply_patch(ModelGraph("p1"), patch)
    assert sum(entity.kind is EntityKind.SYSTEM for entity in next_graph.entities) == 1


def test_duplicate_local_ref_is_rejected_for_system_definition():
    request = _system_request((), revision=0)
    proposal = _system_proposal(entities=[
        {"local_ref": "new:system:1", "name": "系统 A", "payload": _system_payload()},
        {"local_ref": "new:system:1", "name": "系统 B", "payload": _system_payload()},
    ])

    with pytest.raises(ContractViolation, match="duplicate task proposal local_ref"):
        compile_task_proposal(request, proposal)


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
    assert "local_ref" in schema["properties"]["entities"]["items"]["properties"]
    assert "ref" not in schema["properties"]["entities"]["items"]["properties"]
    field_patch = schema["properties"]["updates"]["items"]["properties"]["field_patch"]
    assert field_patch["additionalProperties"] is False
    assert "kind" not in field_patch["properties"]


def test_singleton_payload_schema_is_enforced_at_the_structural_boundary():
    task = next(item for item in task_catalog() if item.id == "stakeholder_requirements")
    payload_schema = output_contract(task)["properties"]["entities"]["items"]["properties"]["payload"]

    assert payload_schema["additionalProperties"] is False
    assert "obligation" in payload_schema["properties"]


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


def test_singleton_task_injects_kind_when_model_omits_it():
    payload = _proposal()
    del payload["entities"][0]["kind"]
    patch = compile_task_proposal(_request(), payload)

    assert patch is not None
    assert patch.operations[0].entity.kind is EntityKind.REQUIREMENT


def test_multi_kind_task_requires_kind():
    task = next(item for item in task_catalog() if len(item.output_kinds) > 1)
    contract = output_contract(task)
    context = ContextBundle("p1", task.id, 3, (make_entity(EntityKind.SYSTEM, "系统"),))
    request = TaskExecutionRequest(task.id, "v2.1", context, (), contract, 100, patch_policy=task.patch_policy)
    payload = _proposal()
    payload["entities"][0].pop("kind")
    with pytest.raises(ContractViolation, match="schema"):
        compile_task_proposal(request, payload)


def test_local_ref_resolves_relation_to_entity_created_in_same_proposal():
    task = next(item for item in task_catalog() if item.id == "function_identification")
    requirement = make_entity(EntityKind.REQUIREMENT, "系统应完成投递", {"obligation": "shall"})
    context = ContextBundle("p1", task.id, 3, (requirement,))
    request = TaskExecutionRequest(
        task.id, "v2.1", context, (), output_contract(task), 100,
        patch_policy=task.patch_policy,
    )
    payload = {
        "entities": [{
            "local_ref": "new:function:1",
            "name": "规划配送路径",
            "payload": {"description": "根据需求规划路径"},
        }],
        "relations": [], "updates": [], "deprecations": [], "reason": "识别功能",
    }
    payload["relations"] = [{
        "source_ref": requirement.id,
        "predicate": "satisfiedBy",
        "target_ref": "new:function:1",
        "evidence_ids": [],
    }]

    patch = compile_task_proposal(request, payload)

    assert patch is not None
    assert isinstance(patch.operations[0], AddEntity)
    assert isinstance(patch.operations[1], Relate)
    assert patch.operations[1].source_id == requirement.id
    assert patch.operations[1].target_id == patch.operations[0].entity.id


def test_local_ref_mapping_is_scoped_to_one_proposal():
    task = next(item for item in task_catalog() if item.id == "function_identification")
    requirement = make_entity(EntityKind.REQUIREMENT, "系统应完成投递", {"obligation": "shall"})
    context = ContextBundle("p1", task.id, 3, (requirement,))
    request = TaskExecutionRequest(
        task.id, "v2.1", context, (), output_contract(task), 100,
        patch_policy=task.patch_policy,
    )
    payload = {
        "entities": [],
        "relations": [{
            "source_ref": requirement.id,
            "predicate": "satisfiedBy",
            "target_ref": "new:function:1",
            "evidence_ids": [],
        }],
        "updates": [], "deprecations": [], "reason": "跨任务引用不应被接受",
    }

    with pytest.raises(ContractViolation, match="unknown"):
        compile_task_proposal(request, payload)


def test_same_proposal_compiles_to_the_same_patch_deterministically():
    request = _request()
    payload = _proposal()

    first = compile_task_proposal(request, payload)
    second = compile_task_proposal(request, payload)

    assert first == second
    assert first is not None
    assert first.id == second.id


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


def test_patch_like_update_fields_are_rejected_by_proposal_schema():
    request = _request()
    payload = _proposal(entities=[])
    payload["updates"] = [{
        "entity_id": request.context_bundle.entities[0].id,
        "field_patch": {"kind": "system", "value": "not-an-entity-update"},
    }]

    with pytest.raises(ContractViolation, match="schema"):
        compile_task_proposal(request, payload)


def _update_request() -> tuple[TaskExecutionRequest, str]:
    request = _request()
    entity = make_entity(
        EntityKind.REQUIREMENT,
        "原始需求",
        {"obligation": "系统应完成投递", "source": "doc-1"},
    )
    contract = dict(request.output_contract)
    schemas = dict(contract["x-payload-schemas"])
    requirement_schema = dict(schemas[EntityKind.REQUIREMENT.value])
    requirement_schema["required"] = ["obligation", "source"]
    schemas[EntityKind.REQUIREMENT.value] = requirement_schema
    contract["x-payload-schemas"] = schemas
    return replace(
        request,
        context_bundle=replace(request.context_bundle, entities=(entity,)),
        output_contract=contract,
    ), entity.id


def test_partial_payload_update_validates_merged_payload():
    request, entity_id = _update_request()
    payload = _proposal(
        entities=[],
        updates=[{
            "entity_id": entity_id,
            "field_patch": {"payload": {"obligation": "系统应支持人工接管"}},
        }],
    )

    patch = compile_task_proposal(request, payload)

    assert patch is not None
    assert isinstance(patch.operations[0], UpdateEntity)
    assert patch.operations[0].field_patch == {
        "payload": {"obligation": "系统应支持人工接管"}
    }


def test_partial_payload_update_rejects_invalid_final_payload():
    request, entity_id = _update_request()
    payload = _proposal(
        entities=[],
        updates=[{
            "entity_id": entity_id,
            "field_patch": {"payload": {"source": 42}},
        }],
    )

    with pytest.raises(ContractViolation, match="invalid requirement payload"):
        compile_task_proposal(request, payload)
