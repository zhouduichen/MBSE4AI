import json
import threading
import time

import pytest

from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import AddEntity, ModelGraph, Relation, Relate, UpdateEntity, apply_patch
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.domain.errors import (
    ProposalCompileFailure,
    StructuredOutputFailure,
    TransportFailure,
)
from rflp_lite.methodology.contracts import ContextBundle, StepStatus, TaskExecutionRequest
from rflp_lite.methodology.executor import TaskExecutor
from rflp_lite.methodology.registries import RetryPolicy
from rflp_lite.methodology.tasks import task_catalog
from rflp_lite.methodology.trace_rules import vv_scope_matches
from rflp_lite.methodology.vertical_generation import stage_task
from rflp_lite.runtime.structured_model import (
    StructuredModelRuntime,
    _r_slice_contract,
    _r_stage_slices,
    _sanitize_vertical_proposal,
)
from rflp_lite.runtime.rule_based import RuleRuntime
from rflp_lite.ports.generative_model import GenerationResponse


class FakeModel:
    def __init__(self, payload=None):
        self.request = None
        self.payload = payload or {
            "entities": [], "relations": [], "updates": [], "deprecations": [], "reason": "无变化",
        }

    def complete_json(self, request):
        self.request = request
        return GenerationResponse("task-1", self.payload, "input", "output", False, "fake", "fake-model")


class CompilerRepairModel:
    def __init__(self):
        self.calls = []

    def complete_json(self, request):
        self.calls.append(request)
        concern = {
            "local_ref": "concern-1",
            "kind": "concern",
            "name": "任务可控",
            "payload": {"topic": "人工接管"},
        }
        stakeholder = {
            "local_ref": "stakeholder-1",
            "kind": "stakeholder",
            "name": "操作员",
            "payload": {"role": "执行任务"},
        }
        target = "missing-concern" if len(self.calls) == 1 else "concern-1"
        return GenerationResponse(
            request.lens_id,
            {
                "entities": [stakeholder, concern],
                "relations": [{
                    "source_ref": "stakeholder-1",
                    "predicate": RelationPredicate.HAS_CONCERN.value,
                    "target_ref": target,
                    "evidence_ids": [],
                }],
                "updates": [],
                "deprecations": [],
                "reason": "补充操作员关注点",
            },
            "input",
            f"output-{len(self.calls)}",
            False,
            "fake",
            "fake-model",
        )


class BatchedVvModel:
    supports_requirement_batching = True

    def __init__(self, *, fail_on_batch: int | None = None):
        self.calls = []
        self.fail_on_batch = fail_on_batch

    def complete_json(self, request):
        batch = request.user_payload["requirement_batch"]
        self.calls.append(request)
        if batch["index"] == self.fail_on_batch:
            raise TransportFailure(
                "batch provider unavailable",
                code="network_error",
                provider_id="fake",
                model_id="fake-model",
            )
        payload = {
            "entities": [],
            "relations": [],
            "updates": [],
            "deprecations": [],
            "reason": f"批次 {batch['index']}",
        }
        for item in request.user_payload["requirement_worklist"]:
            requirement_id = item["requirement_id"]
            suffix = f"{batch['index']}-{requirement_id[-8:]}"
            verification_ref = f"verification-{suffix}"
            validation_ref = f"validation-{suffix}"
            plan = {
                "method": "test",
                "verification_objective": "证明需求满足",
                "precondition": "系统处于初始状态",
                "test_condition": "代表性运行环境",
                "input": "需求输入",
                "stimulus": "施加需求场景",
                "procedure": "执行步骤并记录结果",
                "expected_result": "系统满足需求",
                "pass_criteria": "结果满足需求",
                "requirement_ids": [requirement_id],
                "scenario_ids": [],
                "activity_ids": [],
                "covered_branches": [],
                "evidence_ids": [],
                "execution_evidence_ids": [],
                "function_ids": [],
                "logical_component_ids": [],
                "physical_ids": [],
                "constraint_fields": [],
                "evidence_required": True,
                "open_questions": ["尚未执行测试"],
            }
            payload["entities"].extend((
                {
                    "local_ref": verification_ref,
                    "kind": EntityKind.VERIFICATION_CASE.value,
                    "name": f"验证：{item['statement']}",
                    "payload": {**plan, "cross_analysis_status": "checked"},
                },
                {
                    "local_ref": validation_ref,
                    "kind": EntityKind.VALIDATION_CASE.value,
                    "name": f"确认：{item['statement']}",
                    "payload": plan,
                },
            ))
            payload["relations"].extend((
                {
                    "source_ref": requirement_id,
                    "predicate": RelationPredicate.VERIFIED_BY.value,
                    "target_ref": verification_ref,
                    "evidence_ids": [],
                },
                {
                    "source_ref": requirement_id,
                    "predicate": RelationPredicate.VALIDATED_BY.value,
                    "target_ref": validation_ref,
                    "evidence_ids": [],
                },
            ))
            payload["relations"].append(dict(payload["relations"][-1]))
        return GenerationResponse(
            request.lens_id,
            payload,
            f"input-{batch['index']}",
            f"output-{batch['index']}",
            False,
            "fake",
            "fake-model",
        )


class BatchedVerticalModel:
    supports_requirement_batching = True

    def __init__(self):
        self.calls = []

    def complete_json(self, request):
        self.calls.append(request)
        return GenerationResponse(
            request.lens_id,
            {
                "entities": [],
                "relations": [],
                "updates": [],
                "deprecations": [],
                "reason": "等待当前批次的需求工作项",
            },
            "input",
            f"output-{len(self.calls)}",
            False,
            "fake",
            "fake-model",
        )


class SplitBatchedVvModel(BatchedVvModel):
    """Fail wide V&V calls so the runtime's singleton fallback is exercised."""

    def complete_json(self, request):
        if len(request.user_payload["requirement_worklist"]) > 1:
            self.calls.append(request)
            raise StructuredOutputFailure(
                "batch output truncated",
                code="truncated",
                provider_id="fake",
                model_id="fake-model",
            )
        return super().complete_json(request)


class SingletonVvBatchedModel(BatchedVvModel):
    vertical_vv_batch_size = 1


class CaseSplitVvModel(BatchedVvModel):
    supports_vv_case_splitting = True

    def complete_json(self, request):
        response = super().complete_json(request)
        case_kind = request.user_payload["requirement_batch"]["case_kind"]
        entities = [
            entity
            for entity in response.payload["entities"]
            if entity["kind"] == case_kind
        ]
        refs = {entity["local_ref"] for entity in entities}
        relations = [
            relation
            for relation in response.payload["relations"]
            if relation["target_ref"] in refs
        ]
        return GenerationResponse(
            response.lens_id,
            {
                **response.payload,
                "entities": entities,
                "relations": relations,
            },
            response.input_hash,
            response.output_hash,
            response.repaired,
            response.provider_id,
            response.model_id,
        )


def test_runtime_adapts_task_context_to_generation_request():
    model = FakeModel()
    runtime = StructuredModelRuntime(model)
    task = task_catalog()[1]
    context = ContextBundle("p1", task.id, 3, (make_entity(EntityKind.SYSTEM, "系统"),))

    request = TaskExecutor(model).request(task, context, "v2.0")
    result = runtime.execute(request)

    assert result.status is StepStatus.COMPLETED
    assert model.request.lens_id == task.id
    assert model.request.user_payload["context"]["revision"] == 3


def test_vertical_runtime_exposes_canonical_requirement_worklist():
    model = FakeModel()
    requirements = tuple(
        make_entity(
            EntityKind.REQUIREMENT,
            statement,
            {"statement": statement},
        )
        for statement in (
            "系统应自主配送",
            "系统应支持人工接管",
            "系统应在断网后安全运行",
        )
    )
    context = ContextBundle(
        "p1",
        "vertical.functional",
        3,
        requirements,
        methodology_guidance={
            "requirement_coverage": {
                "gaps": [
                    {
                        "requirement_id": requirements[0].id,
                        "missing": ["function"],
                    },
                    {
                        "requirement_id": requirements[1].id,
                        "missing": ["function"],
                    },
                ],
            },
        },
    )
    request = TaskExecutor(model).request(
        stage_task("functional"),
        context,
        "v2.1",
    )

    StructuredModelRuntime(model).execute(request)

    missing_requirement_ids = {requirements[0].id, requirements[1].id}
    assert model.request.user_payload["requirement_worklist"] == [
        {
            "requirement_id": requirement.id,
            "statement": requirement.payload["statement"],
            "missing": ["function"]
            if requirement.id in missing_requirement_ids
            else [],
        }
        for requirement in sorted(requirements, key=lambda item: item.id)
    ]


def test_r_stage_slices_backbone_then_one_requirement_closure_per_requirement():
    requirements = tuple(
        make_entity(
            EntityKind.REQUIREMENT,
            f"需求 {index}",
            {"statement": f"系统应完成任务 {index}"},
        )
        for index in range(5)
    )
    request = TaskExecutionRequest(
        "vertical.requirements",
        "v2.1",
        ContextBundle("p1", "vertical.requirements", 3, requirements),
        (),
        {"output_kinds": [kind.value for kind in EntityKind]},
        3000,
    )
    payload = {
        "context": {"entities": [], "relations": []},
        "requirement_worklist": [
            {
                "requirement_id": requirement.id,
                "statement": requirement.payload["statement"],
                "missing": ["use_case", "activity"],
            }
            for requirement in requirements
        ],
    }

    slices = _r_stage_slices(request, payload)

    assert [item["r_slice"]["slice_kind"] for item in slices] == [
        "r_backbone_operational",
        "r_backbone_behavior",
        "r_requirement",
        "r_requirement",
        "r_requirement",
        "r_requirement",
        "r_requirement",
    ]
    assert [
        item["r_slice"]["requirement_ids"] for item in slices[2:]
    ] == [[requirement.id] for requirement in requirements]
    assert all(
        "requirement" not in item["r_slice"]["allowed_kinds"]
        for item in slices[:2]
    )


def test_r_stage_slices_can_split_remote_backbone_by_entity_kind():
    request = TaskExecutor(FakeModel()).request(
        stage_task("requirements"),
        ContextBundle("p1", "vertical.requirements", 3, ()),
        "v2.1",
    )
    payload = {
        "context": {"entities": [], "relations": []},
        "requirement_worklist": [
            {
                "requirement_id": "req-1",
                "statement": "系统应支持人工接管",
                "missing": ["use_case", "activity"],
            }
        ],
    }

    slices = _r_stage_slices(request, payload, single_kind=True)

    backbone = [
        item["r_slice"]
        for item in slices
        if item["r_slice"]["slice_kind"] != "r_requirement"
    ]
    assert [item["allowed_kinds"] for item in backbone] == [
        ["system"],
        ["stakeholder"],
        ["concern"],
        ["lifecycle_stage"],
        ["lifecycle_transition"],
        ["scenario_hypothesis"],
        ["use_case"],
        ["operational_scenario"],
        ["activity"],
    ]
    concern_slice = next(
        item for item in slices
        if item["r_slice"]["allowed_kinds"] == ["concern"]
    )
    concern_contract = _r_slice_contract(
        request.output_contract,
        concern_slice,
    )
    assert concern_contract["properties"]["entities"]["maxItems"] == 8


def test_r_requirement_slice_contract_forbids_new_entities_and_scopes_update():
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "系统应支持人工接管",
        {"statement": "系统应支持人工接管"},
    )
    request = TaskExecutor(FakeModel()).request(
        stage_task("requirements"),
        ContextBundle("p1", "vertical.requirements", 3, (requirement,)),
        "v2.1",
    )
    payload = {
        "r_slice": {
            "slice_kind": "r_requirement",
            "allowed_kinds": [],
            "requirement_ids": [requirement.id],
        },
    }

    contract = _r_slice_contract(request.output_contract, payload)
    properties = contract["properties"]
    assert properties["entities"]["maxItems"] == 0
    assert properties["updates"]["items"]["properties"]["entity_id"] == {
        "const": requirement.id,
    }
    assert properties["relations"]["items"]["properties"]["predicate"]["enum"] == [
        "decomposes", "derivedFrom",
    ]


def test_vertical_runtime_keeps_entities_when_relation_reference_is_unresolvable():
    class RScopedModel(FakeModel):
        def complete_json(self, request):
            payload = dict(self.payload)
            kind_schema = (
                request.response_schema
                .get("properties", {})
                .get("entities", {})
                .get("items", {})
                .get("properties", {})
                .get("kind", {})
            )
            entity_schema = request.response_schema.get("properties", {}).get("entities", {})
            if entity_schema.get("maxItems") == 0:
                payload.update(entities=[], relations=[])
                return GenerationResponse(
                    request.lens_id, payload, "input", "output", False, "fake", "fake-model"
                )
            allowed = set(kind_schema.get("enum", ()))
            if allowed:
                entities = [
                    item for item in payload["entities"]
                    if item["kind"] in allowed
                ]
                refs = {item["local_ref"] for item in entities}
                relations = [
                    item for item in payload["relations"]
                    if item["source_ref"] in refs or item["target_ref"] in refs
                ]
                payload.update(entities=entities, relations=relations)
            return GenerationResponse(
                request.lens_id, payload, "input", "output", False, "fake", "fake-model"
            )

    model = RScopedModel({
        "entities": [
            {
                "local_ref": "system-1",
                "kind": EntityKind.SYSTEM.value,
                "name": "系统",
                "payload": {
                    "mission": "完成任务",
                    "system_boundary": {"inside": [], "outside": []},
                    "objectives": [],
                    "environment_assumptions": [],
                    "exclusions": [],
                    "open_questions": [],
                },
            },
            {
                "local_ref": "stakeholder-1",
                "kind": EntityKind.STAKEHOLDER.value,
                "name": "操作员",
                "payload": {"role": "执行任务"},
            },
        ],
        "relations": [{
            "source_ref": "system-1",
            "predicate": RelationPredicate.DECOMPOSES.value,
            "target_ref": "missing-display-name",
            "evidence_ids": [],
        }],
        "updates": [],
        "deprecations": [],
        "reason": "补充运行上下文",
    })
    task = stage_task("requirements")
    context = ContextBundle(
        "p1",
        task.id,
        3,
        (make_entity(EntityKind.REQUIREMENT, "系统应完成任务", {"statement": "系统应完成任务"}),),
    )

    result = StructuredModelRuntime(model).execute(
        TaskExecutor(model).request(task, context, "v2.1")
    )

    assert result.patch is not None
    assert sum(isinstance(operation, AddEntity) for operation in result.patch.operations) == 2
    assert not any(isinstance(operation, Relate) for operation in result.patch.operations)


def test_r_stage_closures_use_canonical_entities_from_the_working_graph():
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "系统应支持人工接管",
        {"statement": "系统应支持人工接管"},
    )

    class WorkingGraphModel:
        def __init__(self):
            self.calls = []

        def complete_json(self, request):
            self.calls.append(request)
            metadata = request.user_payload["r_slice"]
            slice_kind = metadata["slice_kind"]
            entities = []
            relations = []
            if slice_kind == "r_backbone_operational":
                entities = [{
                    "local_ref": "concern-local",
                    "kind": EntityKind.CONCERN.value,
                    "name": "人工接管可控",
                    "payload": {"topic": "人工接管"},
                }]
            elif slice_kind == "r_backbone_behavior":
                assert any(
                    item["kind"] == EntityKind.CONCERN.value
                    for item in request.user_payload["context"]["entities"]
                )
                entities = [{
                    "local_ref": "use-case-local",
                    "kind": EntityKind.USE_CASE.value,
                    "name": "人工接管",
                    "payload": {"goal": "完成人工接管"},
                }]
            else:
                context_entities = request.user_payload["context"]["entities"]
                use_case = next(
                    item for item in context_entities
                    if item["kind"] == EntityKind.USE_CASE.value
                )
                requirement_id = metadata["requirement_ids"][0]
                relations = [{
                    "source_ref": requirement_id,
                    "predicate": RelationPredicate.DERIVED_FROM.value,
                    "target_ref": use_case["id"],
                    "evidence_ids": [],
                }]
            return GenerationResponse(
                request.lens_id,
                {
                    "entities": entities,
                    "relations": relations,
                    "updates": [],
                    "deprecations": [],
                    "reason": slice_kind,
                },
                "input",
                f"output-{len(self.calls)}",
                False,
                "fake",
                "fake-model",
            )

    model = WorkingGraphModel()
    task = stage_task("requirements")
    context = ContextBundle("p1", task.id, 7, (requirement,))
    result = StructuredModelRuntime(model).execute(
        TaskExecutor(model).request(task, context, "v2.1")
    )

    assert result.patch is not None
    assert result.patch.expected_revision == 7
    assert any(
        isinstance(operation, AddEntity)
        and operation.entity.kind is EntityKind.USE_CASE
        for operation in result.patch.operations
    )
    assert any(
        isinstance(operation, Relate)
        and operation.source_id == requirement.id
        and operation.predicate is RelationPredicate.DERIVED_FROM
        and operation.target_id.startswith("use_case-")
        for operation in result.patch.operations
    )
    assert [
        request.user_payload["r_slice"]["slice_kind"]
        for request in model.calls
    ] == [
        "r_backbone_operational",
        "r_backbone_behavior",
        "r_requirement",
    ]


def test_r_stage_parallelizes_independent_backbones_before_requirement_closure():
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "系统应支持人工接管",
        {"statement": "系统应支持人工接管"},
    )

    class ParallelBackboneModel:
        supports_parallel_requirement_batching = True
        supports_parallel_r_backbone = True
        max_parallel_requests = 2

        def __init__(self):
            self.calls = []
            self._lock = threading.Lock()
            self._barrier = threading.Barrier(2)
            self._active = 0
            self.max_active = 0

        def complete_json(self, request):
            metadata = request.user_payload["r_slice"]
            slice_kind = metadata["slice_kind"]
            with self._lock:
                self.calls.append(slice_kind)
            if slice_kind == "r_requirement":
                return GenerationResponse(
                    request.lens_id,
                    {
                        "entities": [],
                        "relations": [],
                        "updates": [],
                        "deprecations": [],
                        "reason": "需求已具备运行上下文",
                    },
                    "input",
                    f"output-{len(self.calls)}",
                    False,
                    "fake",
                    "fake-model",
                )
            with self._lock:
                self._active += 1
                self.max_active = max(self.max_active, self._active)
            try:
                self._barrier.wait(timeout=2)
            finally:
                with self._lock:
                    self._active -= 1
            if slice_kind == "r_backbone_operational":
                entities = [{
                    "local_ref": "system-local",
                    "kind": EntityKind.SYSTEM.value,
                    "name": "任务系统",
                    "payload": {
                        "mission": "完成任务",
                        "system_boundary": {"inside": [], "outside": []},
                        "objectives": [],
                        "environment_assumptions": [],
                        "exclusions": [],
                        "open_questions": [],
                    },
                }]
            else:
                entities = [{
                    "local_ref": "scenario-local",
                    "kind": EntityKind.SCENARIO_HYPOTHESIS.value,
                    "name": "人工接管场景",
                    "payload": {"category": "normal", "text": "执行人工接管"},
                }]
            return GenerationResponse(
                request.lens_id,
                {
                    "entities": entities,
                    "relations": [],
                    "updates": [],
                    "deprecations": [],
                    "reason": slice_kind,
                },
                "input",
                f"output-{len(self.calls)}",
                False,
                "fake",
                "fake-model",
            )

    model = ParallelBackboneModel()
    task = stage_task("requirements")
    request = TaskExecutor(model).request(
        task,
        ContextBundle("p1", task.id, 11, (requirement,)),
        "v2.1",
    )

    result = StructuredModelRuntime(model).execute(request)

    assert result.patch is not None
    assert model.max_active == 2
    assert set(model.calls[:2]) == {
        "r_backbone_operational",
        "r_backbone_behavior",
    }
    assert model.calls[2:] == ["r_requirement"]
    added_kinds = [
        operation.entity.kind
        for operation in result.patch.operations
        if isinstance(operation, AddEntity)
    ]
    assert added_kinds == [EntityKind.SYSTEM, EntityKind.SCENARIO_HYPOTHESIS]


def test_r_stage_parallel_backbone_failure_falls_back_after_successful_peer():
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "系统应支持人工接管",
        {"statement": "系统应支持人工接管"},
    )

    class FallbackBackboneModel:
        supports_parallel_requirement_batching = True
        supports_parallel_r_backbone = True
        max_parallel_requests = 2

        def __init__(self):
            self.calls = []

        def complete_json(self, request):
            metadata = request.user_payload["r_slice"]
            slice_kind = metadata["slice_kind"]
            self.calls.append(slice_kind)
            if slice_kind == "r_backbone_behavior":
                raise StructuredOutputFailure(
                    "mixed backbone rejected",
                    code="schema_validation",
                    provider_id="fake",
                    model_id="fake-model",
                )
            if slice_kind.startswith("r_backbone_behavior:"):
                kind = metadata["allowed_kinds"][0]
                entities = [{
                    "local_ref": "scenario-local",
                    "kind": kind,
                    "name": "人工接管场景",
                    "payload": {"category": "normal", "text": "执行人工接管"},
                }] if kind == EntityKind.SCENARIO_HYPOTHESIS.value else []
            elif slice_kind == "r_backbone_operational":
                entities = [{
                    "local_ref": "concern-local",
                    "kind": EntityKind.CONCERN.value,
                    "name": "人工接管可控",
                    "payload": {"topic": "人工接管"},
                }]
            else:
                entities = []
            return GenerationResponse(
                request.lens_id,
                {
                    "entities": entities,
                    "relations": [],
                    "updates": [],
                    "deprecations": [],
                    "reason": slice_kind,
                },
                "input",
                f"output-{len(self.calls)}",
                False,
                "fake",
                "fake-model",
            )

    model = FallbackBackboneModel()
    task = stage_task("requirements")
    request = TaskExecutor(model).request(
        task,
        ContextBundle("p1", task.id, 11, (requirement,)),
        "v2.1",
    )

    result = StructuredModelRuntime(model).execute(request)

    assert result.patch is not None
    assert set(model.calls[:2]) == {
        "r_backbone_operational",
        "r_backbone_behavior",
    }
    assert model.calls[2:6] == [
        "r_backbone_behavior:scenario_hypothesis",
        "r_backbone_behavior:use_case",
        "r_backbone_behavior:operational_scenario",
        "r_backbone_behavior:activity",
    ]
    assert model.calls[-1] == "r_requirement"
    assert {
        operation.entity.kind
        for operation in result.patch.operations
        if isinstance(operation, AddEntity)
    } == {EntityKind.CONCERN, EntityKind.SCENARIO_HYPOTHESIS}


def test_r_stage_failure_keeps_the_write_boundary_and_stops_closures():
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "系统应支持人工接管",
        {"statement": "系统应支持人工接管"},
    )

    class FailingBackboneModel:
        def __init__(self):
            self.calls = []

        def complete_json(self, request):
            slice_kind = request.user_payload["r_slice"]["slice_kind"]
            self.calls.append(slice_kind)
            if slice_kind.startswith("r_backbone_behavior"):
                raise StructuredOutputFailure(
                    "backbone response truncated",
                    code="truncated",
                    provider_id="fake",
                    model_id="fake-model",
                    finish_reason="length",
                )
            return GenerationResponse(
                request.lens_id,
                {
                    "entities": [],
                    "relations": [],
                    "updates": [],
                    "deprecations": [],
                    "reason": "没有可安全补充的运营骨架",
                },
                "input",
                "output",
                False,
                "fake",
                "fake-model",
            )

    model = FailingBackboneModel()
    task = stage_task("requirements")
    request = TaskExecutor(model).request(
        task,
        ContextBundle("p1", task.id, 11, (requirement,)),
        "v2.1",
    )

    with pytest.raises(StructuredOutputFailure, match="r_slice_failed=r_backbone_behavior"):
        StructuredModelRuntime(model).execute(request)

    assert model.calls == [
        "r_backbone_operational",
        "r_backbone_behavior",
        "r_backbone_behavior:scenario_hypothesis",
    ]


def test_vertical_runtime_compacts_model_context_but_keeps_typed_payload_fields():
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "系统应保持续航",
        {
            "statement": "系统应保持续航",
            "level": "system",
            "fixture_id": "imported-fixture-1",
        },
        source_ids=("document-1",),
        evidence_ids=("evidence-1",),
    )
    system = make_entity(EntityKind.SYSTEM, "无人机系统")
    relation = Relation(
        "relation-1",
        requirement.id,
        RelationPredicate.DERIVED_FROM,
        system.id,
        evidence_ids=("evidence-1",),
    )
    context = ContextBundle(
        "drone",
        "vertical.logical",
        4,
        (requirement, system),
        (relation,),
        methodology_guidance={
            "version": "methodology-guidance.v1",
            "task_id": "vertical.logical",
            "stage_completion": {
                "issue_codes": ["completion_semantic:logical_analysis"],
                "checks": [{
                    "id": "requirement_coverage:logical",
                    "passed": False,
                    "missing_requirement_ids": [requirement.id],
                    "gaps": [{
                        "requirement_id": requirement.id,
                        "missing": ["logical"],
                        "path": [requirement.id, system.id] * 100,
                    }],
                }],
            },
        },
    )
    model = FakeModel()
    request = TaskExecutor(model).request(
        stage_task("logical"),
        context,
        "v2.1",
    )

    StructuredModelRuntime(model).execute(request)

    wire_entity = next(
        item for item in model.request.user_payload["context"]["entities"]
        if item["kind"] == EntityKind.REQUIREMENT.value
    )
    assert set(wire_entity) == {"id", "kind", "name", "payload"}
    assert wire_entity["payload"] == {
        "statement": "系统应保持续航",
        "level": "system",
    }
    assert set(model.request.user_payload["context"]["relations"][0]) == {
        "source_id", "predicate", "target_id",
    }
    completion = model.request.user_payload["methodology_guidance"]["stage_completion"]
    assert completion["checks"][0]["gaps"] == [{
        "requirement_id": requirement.id,
        "missing": ["logical"],
    }]


def test_vertical_runtime_closes_function_links_from_typed_flow_payloads():
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "系统应支持人工接管",
        {"statement": "系统应支持人工接管"},
    )
    model = FakeModel(payload={
        "entities": [
            {
                "local_ref": "function-1",
                "kind": EntityKind.FUNCTION.value,
                "name": "执行人工接管",
                "payload": {"decomposition": ["接收指令", "执行接管"]},
            },
            {
                "local_ref": "flow-1",
                "kind": EntityKind.FUNCTIONAL_FLOW.value,
                "name": "接管状态流",
                "payload": {
                    "source_function_ids": ["function-1"],
                    "target_function_ids": ["function-1"],
                },
            },
            {
                "local_ref": "scenario-1",
                "kind": EntityKind.FUNCTIONAL_SCENARIO.value,
                "name": "人工接管场景",
                "payload": {"function_ids": ["function-1"]},
            },
        ],
        "relations": [{
            "source_ref": requirement.id,
            "predicate": RelationPredicate.SATISFIED_BY.value,
            "target_ref": "function-1",
            "evidence_ids": [],
        }],
        "updates": [],
        "deprecations": [],
        "reason": "补齐功能关系",
    })
    context = ContextBundle("p1", "vertical.functional", 3, (requirement,))
    request = TaskExecutor(model).request(stage_task("functional"), context, "v2.1")

    result = StructuredModelRuntime(model).execute(request)

    assert result.patch is not None
    links = {
        (operation.predicate, operation.source_id, operation.target_id)
        for operation in result.patch.operations
        if isinstance(operation, Relate)
    }
    function_id = next(
        operation.entity.id
        for operation in result.patch.operations
        if isinstance(operation, AddEntity) and operation.entity.kind is EntityKind.FUNCTION
    )
    flow_id = next(
        operation.entity.id
        for operation in result.patch.operations
        if isinstance(operation, AddEntity) and operation.entity.kind is EntityKind.FUNCTIONAL_FLOW
    )
    scenario_id = next(
        operation.entity.id
        for operation in result.patch.operations
        if isinstance(operation, AddEntity) and operation.entity.kind is EntityKind.FUNCTIONAL_SCENARIO
    )
    assert (RelationPredicate.EXCHANGES_WITH, function_id, flow_id) in links
    assert (RelationPredicate.DERIVED_FROM, function_id, scenario_id) in links


def test_vertical_runtime_prefers_full_graph_requirement_worklist():
    model = FakeModel()
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "系统应支持人工接管",
        {"statement": "系统应支持人工接管"},
    )
    context = ContextBundle(
        "p1",
        "vertical.functional",
        3,
        (requirement,),
        methodology_guidance={
            "requirement_worklist": {
                "stage": "functional",
                "passed": False,
                "total_count": 1,
                "truncated": False,
                "items": [{
                    "requirement_id": requirement.id,
                    "statement": "系统应支持人工接管",
                    "current": {
                        "function_ids": [],
                        "logical_component_ids": [],
                        "physical_ids": [],
                        "verification_case_ids": [],
                        "validation_case_ids": [],
                    },
                    "missing": ["function"],
                    "path": [requirement.id],
                }],
            },
        },
    )
    request = TaskExecutor(model).request(stage_task("functional"), context, "v2.1")

    StructuredModelRuntime(model).execute(request)

    assert model.request.user_payload["requirement_worklist"][0]["current"] == {
        "function_ids": [],
        "logical_component_ids": [],
        "physical_ids": [],
        "verification_case_ids": [],
        "validation_case_ids": [],
    }


def test_vertical_runtime_drops_fixture_metadata_from_requirement_updates():
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "系统应安全返航",
        {
            "statement": "系统应安全返航",
            "fixture_id": "drone-low-battery-return",
        },
    )
    model = FakeModel(payload={
        "entities": [{
            "local_ref": "function-1",
            "kind": EntityKind.FUNCTION.value,
            "name": "执行安全返航",
            "payload": {"decomposition": ["监测电量", "规划返航", "执行着陆"]},
        }],
        "relations": [{
            "source_ref": requirement.id,
            "predicate": RelationPredicate.SATISFIED_BY.value,
            "target_ref": "function-1",
            "evidence_ids": [],
        }],
        "updates": [{
            "entity_id": requirement.id,
            "field_patch": {
                "payload": {
                    "fixture_id": "copied-import-metadata",
                    "functional_behavior_ids": ["function-1"],
                    "functional_requirement_status": "derived",
                    "type": "technical",
                },
            },
        }],
        "deprecations": [],
        "reason": "建立需求到功能的回接",
    })
    request = TaskExecutor(RuleRuntime()).request(
        stage_task("functional"),
        ContextBundle("p1", "vertical.functional", 3, (requirement,)),
        "v2.1",
    )

    response = StructuredModelRuntime(model).execute(request)

    assert response.patch is not None
    update = next(
        operation for operation in response.patch.operations
        if isinstance(operation, UpdateEntity)
    )
    assert update.field_patch["payload"] == {
        "functional_behavior_ids": [
            next(operation.entity.id for operation in response.patch.operations if isinstance(operation, AddEntity))
        ],
        "functional_requirement_status": "derived",
    }
    assert "type" not in update.field_patch["payload"]


def test_vertical_runtime_drops_updates_for_unknown_entities_without_losing_vv_entities():
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "系统应安全返航",
        {"statement": "系统应安全返航"},
    )
    request = TaskExecutor(RuleRuntime()).request(
        stage_task("verification_validation"),
        ContextBundle("p1", "vertical.verification_validation", 3, (requirement,)),
        "v2.1",
    )
    validation = {
        "local_ref": "validation-1",
        "kind": EntityKind.VALIDATION_CASE.value,
        "name": "安全返航场景确认",
        "payload": {
            "method": "演示",
            "verification_objective": "确认返航场景达成",
            "precondition": "系统处于待命状态",
            "test_condition": "模拟低电量场景",
            "input": "低电量事件",
            "stimulus": "触发低电量事件",
            "procedure": "执行返航并记录结果",
            "expected_result": "系统完成安全返航",
            "pass_criteria": "返航成功且无异常",
            "requirement_ids": [requirement.id],
        },
    }
    sanitized = _sanitize_vertical_proposal(
        request,
        {
            "entities": [validation],
            "relations": [],
            "updates": [{
                "entity_id": "validation-not-yet-canonical",
                "field_patch": {"payload": {"execution_evidence_ids": []}},
            }],
            "deprecations": [],
            "reason": "建立验证计划",
        },
    )

    assert sanitized["entities"] == [validation]
    assert sanitized["updates"] == []


def test_vertical_runtime_drops_empty_risk_entities_before_semantic_validation():
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "系统应安全返航",
        {"statement": "系统应安全返航"},
    )
    request = TaskExecutor(RuleRuntime()).request(
        stage_task("verification_validation"),
        ContextBundle("p1", "vertical.verification_validation", 3, (requirement,)),
        "v2.1",
    )
    valid_case = {
        "local_ref": "verification-1",
        "kind": EntityKind.VERIFICATION_CASE.value,
        "name": "安全返航验证",
        "payload": {
            "method": "test",
            "verification_objective": "验证安全返航",
            "precondition": "系统飞行中",
            "test_condition": "注入低电量",
            "input": "低电量事件",
            "stimulus": "触发低电量",
            "procedure": "观察返航",
            "expected_result": "系统返航",
            "pass_criteria": "返航成功",
            "requirement_ids": [requirement.id],
        },
    }
    sanitized = _sanitize_vertical_proposal(
        request,
        {
            "entities": [
                valid_case,
                {
                    "local_ref": "empty-failure",
                    "kind": EntityKind.FAILURE_MODE.value,
                    "name": "空失效模式",
                    "payload": {},
                },
            ],
            "relations": [{
                "source_ref": "empty-failure",
                "predicate": RelationPredicate.CAUSES.value,
                "target_ref": "verification-1",
            }],
            "updates": [],
            "deprecations": [],
            "reason": "建立验证计划",
        },
    )

    assert sanitized["entities"] == [valid_case]
    assert all(
        relation["predicate"] != RelationPredicate.CAUSES.value
        for relation in sanitized["relations"]
    )
    assert any(
        relation["predicate"] == RelationPredicate.VERIFIED_BY.value
        and relation["target_ref"] == "verification-1"
        for relation in sanitized["relations"]
    )


def test_vertical_runtime_drops_unknown_typed_payload_ids_without_discarding_entity():
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "系统应保持续航",
        {"statement": "系统应保持续航"},
    )
    function = make_entity(EntityKind.FUNCTION, "维持续航")
    request = TaskExecutor(RuleRuntime()).request(
        stage_task("logical"),
        ContextBundle("p1", "vertical.logical", 3, (requirement, function)),
        "v2.1",
    )
    logical = {
        "local_ref": "logical-1",
        "kind": EntityKind.LOGICAL_COMPONENT.value,
        "name": "续航管理逻辑组件",
        "payload": {
            "responsibility": "管理续航",
            "function_id": function.id,
            "functional_flow_ids": ["flow-that-was-never-declared"],
            "dependencies": ["component-that-was-never-declared"],
        },
    }

    sanitized = _sanitize_vertical_proposal(
        request,
        {
            "entities": [logical],
            "relations": [],
            "updates": [],
            "deprecations": [],
            "reason": "建立续航逻辑组件",
        },
    )

    assert sanitized["entities"][0]["payload"] == {
        "responsibility": "管理续航",
        "function_id": function.id,
        "functional_flow_ids": [],
        "dependencies": [],
    }


def test_vertical_runtime_drops_import_only_entity_metadata_before_compilation():
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "系统应保持续航",
        {"statement": "系统应保持续航", "metric": {"value": 12}},
    )
    request = TaskExecutor(RuleRuntime()).request(
        stage_task("requirements"),
        ContextBundle("p1", "vertical.requirements", 3, (requirement,)),
        "v2.1",
    )
    proposal = {
        "entities": [{
            "local_ref": "requirement-derived",
            "kind": EntityKind.REQUIREMENT.value,
            "name": "派生续航需求",
            "payload": {
                "statement": "系统应保持续航",
                "metric": {"name": "runtime", "value": 12},
                "fault_injection_id": "REQ-RUNTIME",
            },
        }],
        "relations": [],
        "updates": [],
        "deprecations": [],
        "reason": "保留需求语义",
    }

    sanitized = _sanitize_vertical_proposal(request, proposal)

    assert sanitized["entities"][0]["payload"] == {
        "statement": "系统应保持续航",
    }


def test_vertical_runtime_preserves_context_scoped_traceability_metadata():
    model = FakeModel()
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "系统应自主配送",
        {"statement": "系统应自主配送"},
    )
    function_id = "function-not-loaded"
    context = ContextBundle(
        "p1",
        "vertical.functional",
        3,
        (requirement,),
        methodology_guidance={
            "requirement_worklist": {
                "stage": "functional",
                "passed": False,
                "total_count": 1,
                "truncated": False,
                "items": [{
                    "requirement_id": requirement.id,
                    "statement": "系统应自主配送",
                    "current": {
                        "function_ids": [function_id],
                        "logical_component_ids": [],
                        "physical_ids": [],
                        "verification_case_ids": [],
                        "validation_case_ids": [],
                    },
                    "available_current": {
                        "function_ids": [],
                        "logical_component_ids": [],
                        "physical_ids": [],
                        "verification_case_ids": [],
                        "validation_case_ids": [],
                    },
                    "unavailable_current": {
                        "function_ids": [function_id],
                        "logical_component_ids": [],
                        "physical_ids": [],
                        "verification_case_ids": [],
                        "validation_case_ids": [],
                    },
                    "missing": ["function"],
                    "path": [requirement.id, function_id],
                }],
            },
        },
    )

    request = TaskExecutor(model).request(
        stage_task("functional"),
        context,
        "v2.1",
    )
    StructuredModelRuntime(model).execute(request)

    item = model.request.user_payload["requirement_worklist"][0]
    assert item["available_current"]["function_ids"] == []
    assert item["unavailable_current"]["function_ids"] == [function_id]


def test_vertical_runtime_does_not_drop_requirements_from_full_worklist():
    model = FakeModel()
    requirements = tuple(
        make_entity(
            EntityKind.REQUIREMENT,
            f"需求-{index}",
            {"statement": f"系统应完成任务-{index}"},
        )
        for index in range(25)
    )
    context = ContextBundle(
        "p1",
        "vertical.functional",
        3,
        requirements,
        methodology_guidance={
            "requirement_worklist": {
                "stage": "functional",
                "passed": False,
                "total_count": len(requirements),
                "truncated": False,
                "items": [
                    {
                        "requirement_id": requirement.id,
                        "statement": requirement.payload["statement"],
                        "current": {
                            "function_ids": [],
                            "logical_component_ids": [],
                            "physical_ids": [],
                            "verification_case_ids": [],
                            "validation_case_ids": [],
                        },
                        "missing": ["function"],
                        "path": [requirement.id],
                    }
                    for requirement in requirements
                ],
            },
        },
    )

    request = TaskExecutor(model).request(
        stage_task("functional"),
        context,
        "v2.1",
    )
    StructuredModelRuntime(model).execute(request)

    assert len(model.request.user_payload["requirement_worklist"]) == 25
    assert {
        item["requirement_id"]
        for item in model.request.user_payload["requirement_worklist"]
    } == {requirement.id for requirement in requirements}


def test_legacy_runtime_does_not_add_vertical_requirement_worklist():
    model = FakeModel()
    task = task_catalog()[1]
    context = ContextBundle(
        "p1",
        task.id,
        3,
        (make_entity(EntityKind.REQUIREMENT, "系统需求"),),
    )

    StructuredModelRuntime(model).execute(
        TaskExecutor(model).request(task, context, "v2.1")
    )

    assert "requirement_worklist" not in model.request.user_payload


def test_structured_runtime_batches_large_vv_worklist_and_merges_patch():
    model = BatchedVvModel()
    requirements = tuple(
        make_entity(
            EntityKind.REQUIREMENT,
            f"需求 {index}",
            {
                "statement": f"系统应满足需求 {index}",
                "obligation": "shall",
                "level": "system",
                "type": "functional",
                "verification_method": "test",
            },
        )
        for index in range(5)
    )
    context = ContextBundle("p1", "vertical.verification_validation", 3, requirements)
    request = TaskExecutor(model).request(
        stage_task("verification_validation"), context, "v2.1", token_budget=2048
    )
    ordered_requirements = tuple(sorted(requirements, key=lambda item: item.id))

    result = StructuredModelRuntime(model).execute(request)

    assert result.patch is not None
    assert [
        request.user_payload["requirement_worklist"] for request in model.calls
    ] == [
        [{
            "requirement_id": item.id,
            "statement": item.payload["statement"],
            "missing": [],
        } for item in batch]
        for batch in (
            ordered_requirements[:2],
            ordered_requirements[2:4],
            ordered_requirements[4:],
        )
    ]
    assert [request.user_payload["requirement_batch"] for request in model.calls] == [
        {
            "index": index,
            "count": 3,
            "is_first": index == 1,
            "requirement_ids": [item.id for item in batch],
        }
        for index, batch in enumerate(
            (ordered_requirements[:2], ordered_requirements[2:4], ordered_requirements[4:]),
            start=1,
        )
    ]
    added = [
        operation.entity
        for operation in result.patch.operations
        if hasattr(operation, "entity")
    ]
    assert sum(item.kind is EntityKind.VERIFICATION_CASE for item in added) == 5
    assert sum(item.kind is EntityKind.VALIDATION_CASE for item in added) == 5
    relation_keys = [
        (operation.source_id, operation.predicate, operation.target_id)
        for operation in result.patch.operations
        if hasattr(operation, "source_id")
    ]
    assert len(relation_keys) == 10
    assert len(relation_keys) == len(set(relation_keys))
    assert "batch_count=3" in result.diagnostics


def test_structured_runtime_can_use_singleton_vv_batches_for_large_outputs():
    model = SingletonVvBatchedModel()
    requirements = tuple(
        make_entity(
            EntityKind.REQUIREMENT,
            f"需求 {index}",
            {
                "statement": f"系统应满足需求 {index}",
                "obligation": "shall",
                "level": "system",
                "type": "functional",
                "verification_method": "test",
            },
        )
        for index in range(5)
    )
    context = ContextBundle("p1", "vertical.verification_validation", 3, requirements)
    request = TaskExecutor(model).request(
        stage_task("verification_validation"), context, "v2.1", token_budget=4096
    )

    result = StructuredModelRuntime(model).execute(request)

    assert result.patch is not None
    assert [
        len(call.user_payload["requirement_worklist"])
        for call in model.calls
    ] == [1, 1, 1, 1, 1]
    assert "batch_count=5" in result.diagnostics


def test_structured_runtime_splits_remote_vv_by_case_kind():
    model = CaseSplitVvModel()
    requirements = tuple(
        make_entity(
            EntityKind.REQUIREMENT,
            f"需求 {index}",
            {
                "statement": f"系统应满足需求 {index}",
                "obligation": "shall",
                "level": "system",
                "type": "functional",
                "verification_method": "test",
            },
        )
        for index in range(3)
    )
    context = ContextBundle("p1", "vertical.verification_validation", 3, requirements)
    request = TaskExecutor(model).request(
        stage_task("verification_validation"), context, "v2.1", token_budget=4096
    )

    result = StructuredModelRuntime(model).execute(request)

    assert result.patch is not None
    assert len(model.calls) == 6
    assert all(len(call.user_payload["requirement_worklist"]) == 1 for call in model.calls)
    assert {
        call.user_payload["requirement_batch"]["case_kind"]
        for call in model.calls
    } == {"verification_case", "validation_case"}
    assert all(
        call.response_schema["properties"]["entities"]["items"]["properties"]["kind"]["const"] == (
            call.user_payload["requirement_batch"]["case_kind"]
        )
        for call in model.calls
    )
    assert all(
        "requirement_ids"
        in call.response_schema["properties"]["entities"]["items"]["properties"][
            "payload"
        ]["required"]
        for call in model.calls
    )
    assert all(
        call.user_payload["requirement_batch"]["requirement_ids"]
        == [call.user_payload["requirement_worklist"][0]["requirement_id"]]
        for call in model.calls
    )
    assert sum(
        operation.entity.kind is EntityKind.VERIFICATION_CASE
        for operation in result.patch.operations
        if isinstance(operation, AddEntity)
    ) == 3
    assert sum(
        operation.entity.kind is EntityKind.VALIDATION_CASE
        for operation in result.patch.operations
        if isinstance(operation, AddEntity)
    ) == 3


def test_structured_runtime_caps_only_multi_requirement_batch_output_budget():
    model = BatchedVerticalModel()
    requirements = tuple(
        make_entity(
            EntityKind.REQUIREMENT,
            f"需求 {index}",
            {"statement": f"系统应满足需求 {index}"},
        )
        for index in range(5)
    )
    context = ContextBundle("p1", "vertical.functional", 3, requirements)
    request = TaskExecutor(model).request(
        stage_task("functional"), context, "v2.1", token_budget=4096
    )

    StructuredModelRuntime(model).execute(request)

    assert [call.max_tokens for call in model.calls] == [3072] * 5


def test_structured_runtime_batches_functional_one_requirement_per_call():
    model = BatchedVerticalModel()
    requirements = tuple(
        make_entity(
            EntityKind.REQUIREMENT,
            f"需求-{index}",
            {"statement": f"系统应满足需求-{index}"},
        )
        for index in range(5)
    )
    request = TaskExecutor(model).request(
        stage_task("functional"),
        ContextBundle("p1", "vertical.functional", 3, requirements),
        "v2.1",
    )

    StructuredModelRuntime(model).execute(request)

    ordered = sorted(requirements, key=lambda item: item.id)
    assert [
        len(call.user_payload["requirement_worklist"])
        for call in model.calls
    ] == [1] * 5
    assert [
        call.user_payload["requirement_batch"]["requirement_ids"]
        for call in model.calls
    ] == [[item.id] for item in ordered]


def test_functional_slice_preserves_requirement_source_and_satisfied_by_trace():
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "系统应支持人工接管",
        {"statement": "系统应支持人工接管"},
    )

    class FunctionalTraceModel:
        def complete_json(self, request):
            requirement_id = request.user_payload["requirement_worklist"][0][
                "requirement_id"
            ]
            return GenerationResponse(
                request.lens_id,
                {
                    "entities": [{
                        "local_ref": "function-intervene",
                        "kind": EntityKind.FUNCTION.value,
                        "name": "执行人工接管",
                        "payload": {
                            "decomposition": ["接收接管指令", "切换安全控制"],
                            "source_requirement_ids": [requirement_id],
                        },
                    }],
                    "relations": [{
                        "source_ref": requirement_id,
                        "predicate": RelationPredicate.SATISFIED_BY.value,
                        "target_ref": "function-intervene",
                        "evidence_ids": [],
                    }],
                    "updates": [],
                    "deprecations": [],
                    "reason": "建立需求到功能的追溯",
                },
                "input",
                "output",
                False,
                "fake",
                "functional-trace-model",
            )

    request = TaskExecutor(FunctionalTraceModel()).request(
        stage_task("functional"),
        ContextBundle("p1", "vertical.functional", 3, (requirement,)),
        "v2.1",
    )
    result = StructuredModelRuntime(FunctionalTraceModel()).execute(request)

    assert result.patch is not None
    function = next(
        operation.entity
        for operation in result.patch.operations
        if isinstance(operation, AddEntity)
        and operation.entity.kind is EntityKind.FUNCTION
    )
    assert function.payload["source_requirement_ids"] == [requirement.id]
    assert any(
        isinstance(operation, Relate)
        and operation.source_id == requirement.id
        and operation.predicate is RelationPredicate.SATISFIED_BY
        and operation.target_id == function.id
        for operation in result.patch.operations
    )


@pytest.mark.parametrize("stage", ("functional", "logical", "physical"))
def test_structured_runtime_batches_large_rflp_worklist(stage):
    model = BatchedVerticalModel()
    requirements = tuple(
        make_entity(
            EntityKind.REQUIREMENT,
            f"需求 {index}",
            {"statement": f"系统应满足需求 {index}"},
        )
        for index in range(5)
    )
    context = ContextBundle("p1", f"vertical.{stage}", 3, requirements)
    request = TaskExecutor(model).request(
        stage_task(stage), context, "v2.1", token_budget=2048
    )

    result = StructuredModelRuntime(model).execute(request)

    ordered_requirements = tuple(sorted(requirements, key=lambda item: item.id))
    expected_batches = (
        tuple((item,) for item in ordered_requirements)
        if stage in {"functional", "logical", "physical"}
        else (
            ordered_requirements[:2],
            ordered_requirements[2:4],
            ordered_requirements[4:],
        )
    )
    assert result.patch is None
    assert [
        [item["requirement_id"] for item in call.user_payload["requirement_worklist"]]
        for call in model.calls
    ] == [
        [item.id for item in batch]
        for batch in expected_batches
    ]
    assert [call.user_payload["requirement_batch"] for call in model.calls] == [
        {
            "index": index,
            "count": len(expected_batches),
            "is_first": index == 1,
            "requirement_ids": [item.id for item in batch],
        }
        for index, batch in enumerate(expected_batches, start=1)
    ]
    assert all(
        (
            "当前是 Functional 第" if stage == "functional"
            else "当前是 Logical 第" if stage == "logical"
            else "当前是 Physical 第" if stage == "physical"
            else f"当前是 vertical.{stage} 第"
        ) in call.system_prompt
        for call in model.calls
    )
    assert f"batch_count={len(expected_batches)}" in result.diagnostics


def test_structured_runtime_accepts_provider_batch_budget_overrides():
    model = BatchedVerticalModel()
    model.vertical_batch_size = 4
    model.vertical_functional_batch_size = 4
    model.vertical_batch_output_token_budget = 1536
    requirements = tuple(
        make_entity(
            EntityKind.REQUIREMENT,
            f"需求 {index}",
            {"statement": f"系统应满足需求 {index}"},
        )
        for index in range(5)
    )
    context = ContextBundle("p1", "vertical.functional", 3, requirements)
    request = TaskExecutor(model).request(
        stage_task("functional"), context, "v2.1", token_budget=4096
    )

    StructuredModelRuntime(model).execute(request)

    assert [
        [item["requirement_id"] for item in call.user_payload["requirement_worklist"]]
        for call in model.calls
    ] == [
        [item.id for item in sorted(requirements, key=lambda item: item.id)[:4]],
        [item.id for item in sorted(requirements, key=lambda item: item.id)[4:]],
    ]
    assert [call.max_tokens for call in model.calls] == [1536, 1536]


def test_structured_runtime_scopes_each_batch_to_current_requirements():
    model = BatchedVerticalModel()
    requirements = tuple(
        make_entity(
            EntityKind.REQUIREMENT,
            f"需求 {index}",
            {"statement": f"系统应满足需求 {index}"},
        )
        for index in range(5)
    )
    system = make_entity(EntityKind.SYSTEM, "系统")
    relation = Relation(
        "relation-1",
        requirements[0].id,
        RelationPredicate.DERIVED_FROM,
        system.id,
    )
    context = ContextBundle(
        "p1",
        "vertical.functional",
        3,
        (*requirements, system),
        (relation,),
    )
    request = TaskExecutor(model).request(
        stage_task("functional"), context, "v2.1", token_budget=2048
    )

    StructuredModelRuntime(model).execute(request)

    ordered_requirements = tuple(sorted(requirements, key=lambda item: item.id))
    for call, expected in zip(
        model.calls,
        tuple((item,) for item in ordered_requirements),
    ):
        expected_ids = {item.id for item in expected}
        visible_requirements = {
            item["id"]
            for item in call.user_payload["context"]["entities"]
            if item["kind"] == EntityKind.REQUIREMENT.value
        }
        assert visible_requirements == expected_ids
        assert system.id in {
            item["id"] for item in call.user_payload["context"]["entities"]
        }
        visible_relations = call.user_payload["context"]["relations"]
        assert bool(visible_relations) is (requirements[0].id in expected_ids)


def test_structured_runtime_retries_failed_batch_as_single_requirements():
    model = SplitBatchedVvModel()
    requirements = tuple(
        make_entity(
            EntityKind.REQUIREMENT,
            f"需求 {index}",
            {"statement": f"系统应满足需求 {index}"},
        )
        for index in range(5)
    )
    context = ContextBundle("p1", "vertical.verification_validation", 3, requirements)
    request = TaskExecutor(model).request(
        stage_task("verification_validation"), context, "v2.1", token_budget=4096
    )

    result = StructuredModelRuntime(model).execute(request)

    assert result.patch is not None
    assert len(model.calls) == 7
    assert [call.max_tokens for call in model.calls] == [3072, 3072, 3072, 2048, 2048, 2048, 2048]
    assert "batch_fallback=single_requirement" in result.diagnostics
    assert sum(
        operation.entity.kind is EntityKind.VERIFICATION_CASE
        for operation in result.patch.operations
        if isinstance(operation, AddEntity)
    ) == 5
    assert sum(
        operation.entity.kind is EntityKind.VALIDATION_CASE
        for operation in result.patch.operations
        if isinstance(operation, AddEntity)
    ) == 5


def test_structured_runtime_parallelizes_batches_only_for_capable_models():
    class ParallelBatchedModel(BatchedVerticalModel):
        supports_parallel_requirement_batching = True

        def __init__(self):
            super().__init__()
            self.thread_ids = set()

        def complete_json(self, request):
            self.thread_ids.add(threading.get_ident())
            time.sleep(0.05)
            return super().complete_json(request)

    model = ParallelBatchedModel()
    model.max_parallel_requests = 3
    requirements = tuple(
        make_entity(
            EntityKind.REQUIREMENT,
            f"需求 {index}",
            {"statement": f"系统应满足需求 {index}"},
        )
        for index in range(5)
    )
    context = ContextBundle("p1", "vertical.functional", 3, requirements)
    request = TaskExecutor(model).request(
        stage_task("functional"), context, "v2.1", token_budget=2048
    )

    result = StructuredModelRuntime(model).execute(request)

    assert result.patch is None
    assert len(model.calls) == 5
    assert len(model.thread_ids) >= 2


def test_structured_runtime_retries_one_failed_parallel_transport_batch():
    class RetryParallelModel(BatchedVerticalModel):
        supports_parallel_requirement_batching = True

        def __init__(self, failed_requirement_id):
            super().__init__()
            self.max_parallel_requests = 3
            self.failed_requirement_id = failed_requirement_id
            self.attempts = {}

        def complete_json(self, request):
            requirement_id = request.user_payload["requirement_worklist"][0][
                "requirement_id"
            ]
            attempt = self.attempts.get(requirement_id, 0) + 1
            self.attempts[requirement_id] = attempt
            if requirement_id == self.failed_requirement_id and attempt == 1:
                self.calls.append(request)
                raise TransportFailure(
                    "transient batch reset",
                    code="network_error",
                    provider_id="fake",
                    model_id="fake-model",
                )
            return super().complete_json(request)

    requirements = tuple(
        make_entity(
            EntityKind.REQUIREMENT,
            f"需求 {index}",
            {"statement": f"系统应满足需求 {index}"},
        )
        for index in range(5)
    )
    model = RetryParallelModel(requirements[0].id)
    request = TaskExecutor(model).request(
        stage_task("functional"),
        ContextBundle("p1", "vertical.functional", 3, requirements),
        "v2.1",
    )

    result = StructuredModelRuntime(model).execute(request)

    assert result.patch is None
    assert model.attempts[requirements[0].id] == 2
    assert len(model.calls) == 6
    assert set(model.attempts) == {item.id for item in requirements}


def test_structured_runtime_rejects_merged_vv_patch_over_effective_limit():
    model = BatchedVvModel()
    requirements = tuple(
        make_entity(EntityKind.REQUIREMENT, f"需求 {index}", {"statement": f"需求 {index}"})
        for index in range(9)
    )
    context = ContextBundle("p1", "vertical.verification_validation", 3, requirements)
    request = TaskExecutor(model).request(
        stage_task("verification_validation"), context, "v2.1"
    )

    with pytest.raises(ProposalCompileFailure) as error:
        StructuredModelRuntime(model).execute(request)

    assert error.value.code == "batch_operation_limit"
    assert len(model.calls) == 5


def test_structured_runtime_discards_partial_vv_batches_on_failure():
    model = BatchedVvModel(fail_on_batch=2)
    requirements = tuple(
        make_entity(EntityKind.REQUIREMENT, f"需求 {index}", {"statement": f"需求 {index}"})
        for index in range(5)
    )
    context = ContextBundle("p1", "vertical.verification_validation", 3, requirements)
    request = TaskExecutor(model).request(
        stage_task("verification_validation"), context, "v2.1"
    )

    with pytest.raises(TransportFailure, match="batch provider unavailable"):
        StructuredModelRuntime(model).execute(request)

    assert len(model.calls) == 2


def test_runtime_turns_allowed_output_into_patch():
    model = FakeModel({
        "entities": [{"local_ref": "e1", "name": "支持配送", "payload": {"source": "doc-1"}}],
        "relations": [], "updates": [], "deprecations": [],
        "reason": "从资料提取系统需求",
    })
    runtime = StructuredModelRuntime(model)
    task = next(item for item in task_catalog() if item.id == "stakeholder_requirements")
    context = ContextBundle("p1", task.id, 3, (make_entity(EntityKind.SYSTEM, "系统"),))
    request = TaskExecutor(model).request(task, context, "v2.0")

    result = runtime.execute(request)

    assert result.patch is not None
    assert result.patch.expected_revision == 3
    assert result.patch.operations[0].entity.kind is EntityKind.REQUIREMENT


def test_runtime_repairs_a_compilable_proposal_after_reference_feedback():
    model = CompilerRepairModel()
    runtime = StructuredModelRuntime(model)
    task = next(item for item in task_catalog() if item.id == "stakeholder_analysis")
    context = ContextBundle("p1", task.id, 3, (make_entity(EntityKind.SYSTEM, "系统"),))

    result = runtime.execute(TaskExecutor(model).request(task, context, "v2.0"))

    assert result.patch is not None
    assert len(model.calls) == 2
    assert "compiler:repaired" in result.diagnostics
    concern_id = next(
        operation.entity.id
        for operation in result.patch.operations
        if hasattr(operation, "entity")
        and operation.entity.kind is EntityKind.CONCERN
    )
    assert any(
        operation.target_id == concern_id
        for operation in result.patch.operations
        if hasattr(operation, "target_id")
    )


def test_runtime_returns_stage_review_metadata():
    model = FakeModel({
        "entities": [], "relations": [], "updates": [], "deprecations": [],
        "reason": "补充阶段假设",
        "assumptions": ["校园网络可用"],
        "open_questions": ["是否允许夜间配送"],
        "decision_records": [{
            "step": "architecture_evaluation",
            "decision": "保留逻辑边界",
            "basis": ["function-1", "flow-1"],
        }],
    })
    runtime = StructuredModelRuntime(model)
    task = task_catalog()[1]
    context = ContextBundle("p1", task.id, 3, (make_entity(EntityKind.SYSTEM, "系统"),))

    result = runtime.execute(TaskExecutor(model).request(task, context, "v2.0"))

    assert result.assumptions == ("校园网络可用",)
    assert result.open_questions == ("是否允许夜间配送",)
    assert result.decision_records == ({
        "step": "architecture_evaluation",
        "decision": "保留逻辑边界",
        "basis": ["function-1", "flow-1"],
    },)


def test_rule_runtime_enriches_existing_system_instead_of_adding_one():
    task = task_catalog()[0]
    system = make_entity(EntityKind.SYSTEM, "系统")
    context = ContextBundle("p1", task.id, 3, (system,))
    request = TaskExecutor(lambda request: None).request(task, context, "v2.1")

    response = RuleRuntime().execute(request)

    assert response.patch is not None
    assert len(response.patch.operations) == 1
    assert isinstance(response.patch.operations[0], UpdateEntity)
    assert response.patch.operations[0].entity_id == system.id


def test_rule_runtime_traces_late_requirements_to_functions_and_vv():
    requirement = make_entity(EntityKind.REQUIREMENT, "原始需求")
    function = make_entity(EntityKind.FUNCTION, "执行功能")
    verification = make_entity(EntityKind.VERIFICATION_CASE, "验证用例")
    validation = make_entity(EntityKind.VALIDATION_CASE, "确认用例")
    context = ContextBundle(
        "p1",
        "reverse_feasibility",
        3,
        (requirement, function, verification, validation),
    )
    task = next(item for item in task_catalog() if item.id == "reverse_feasibility")
    response = RuleRuntime().execute(TaskExecutor(RuleRuntime()).request(task, context, "v2.1"))

    assert response.patch is not None
    added = next(
        operation.entity
        for operation in response.patch.operations
        if hasattr(operation, "entity") and operation.entity.kind is EntityKind.REQUIREMENT
    )
    relations = {
        (operation.source_id, operation.predicate, operation.target_id)
        for operation in response.patch.operations
        if hasattr(operation, "predicate")
    }
    assert (added.id, RelationPredicate.SATISFIED_BY, function.id) in relations
    assert any(
        source_id == added.id and predicate is RelationPredicate.VERIFIED_BY
        for source_id, predicate, _target_id in relations
    )
    assert any(
        source_id == added.id and predicate is RelationPredicate.VALIDATED_BY
        for source_id, predicate, _target_id in relations
    )


def test_reverse_feasibility_gives_late_requirements_scoped_vv_cases():
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "原始需求",
        {"statement": "系统应完成配送"},
    )
    function = make_entity(EntityKind.FUNCTION, "执行功能")
    verification = make_entity(
        EntityKind.VERIFICATION_CASE,
        "验证原始需求",
        {
            "requirement_id": requirement.id,
            "requirement_ids": [requirement.id],
            "function_ids": [function.id],
            "logical_component_ids": [],
            "physical_ids": [],
        },
    )
    validation = make_entity(
        EntityKind.VALIDATION_CASE,
        "确认原始需求",
        {
            "requirement_id": requirement.id,
            "requirement_ids": [requirement.id],
            "function_ids": [function.id],
            "logical_component_ids": [],
            "physical_ids": [],
        },
    )
    context = ContextBundle(
        "p1",
        "reverse_feasibility",
        3,
        (requirement, function, verification, validation),
        (
            Relation("seed-r-to-f", requirement.id, RelationPredicate.SATISFIED_BY, function.id),
        ),
    )
    task = next(item for item in task_catalog() if item.id == "reverse_feasibility")
    request = TaskExecutor(RuleRuntime()).request(task, context, "v2.1")

    response = RuleRuntime().execute(request)

    assert response.patch is not None
    graph = apply_patch(
        ModelGraph("p1", context.entities, context.relations, context.revision),
        response.patch,
    )
    reverse = next(
        item
        for item in graph.entities
        if item.kind is EntityKind.REQUIREMENT
        and item.payload.get("source") == "reverse_feasibility"
    )
    linked_cases = {
        relation.target_id: graph.entity_index[relation.target_id]
        for relation in graph.relations
        if relation.source_id == reverse.id
        and relation.predicate in {
            RelationPredicate.VERIFIED_BY,
            RelationPredicate.VALIDATED_BY,
        }
    }

    assert linked_cases
    assert all(vv_scope_matches(graph, reverse.id, case) for case in linked_cases.values())


def test_global_cross_analysis_repairs_vv_links_for_late_requirements():
    requirements = (
        make_entity(EntityKind.REQUIREMENT, "原始需求"),
        make_entity(EntityKind.REQUIREMENT, "后置需求"),
    )
    verification = make_entity(EntityKind.VERIFICATION_CASE, "验证用例")
    validation = make_entity(EntityKind.VALIDATION_CASE, "确认用例")
    task = next(item for item in task_catalog() if item.id == "global_cross_analysis")
    context = ContextBundle("p1", task.id, 3, (*requirements, verification, validation))

    response = RuleRuntime().execute(TaskExecutor(RuleRuntime()).request(task, context, "v2.1"))

    assert response.patch is not None
    graph = apply_patch(
        ModelGraph("p1", context.entities, context.relations, context.revision),
        response.patch,
    )
    assert all(
        any(
            relation.source_id == requirement.id
            and relation.predicate is RelationPredicate.VERIFIED_BY
            and vv_scope_matches(graph, requirement.id, graph.entity_index[relation.target_id])
            for relation in graph.relations
        )
        and any(
            relation.source_id == requirement.id
            and relation.predicate is RelationPredicate.VALIDATED_BY
            and vv_scope_matches(graph, requirement.id, graph.entity_index[relation.target_id])
            for relation in graph.relations
        )
        for requirement in requirements
    )
    assert all(
        graph.entity_index[relation.target_id].payload.get("cross_analysis_status") == "checked"
        for relation in graph.relations
        if relation.predicate is RelationPredicate.VERIFIED_BY
    )


def test_failure_diagnostics_store_excerpt_hash_and_size_not_unbounded_raw():
    class FailingRuntime:
        def execute(self, _request):
            raise StructuredOutputFailure(
                "invalid proposal",
                raw_response="x" * 3000,
                initial_raw_response="initial",
                schema_hash="schema-hash",
                retry_count=1,
                provider_id="ollama",
                model_id="qwen",
                finish_reason="length",
                usage={"eval_count": 12},
            )

    task = task_catalog()[0]
    context = ContextBundle("p1", task.id, 3, (make_entity(EntityKind.SYSTEM, "系统"),))
    response = TaskExecutor(FailingRuntime()).execute(
        task, context, "v2.1", retry_policy=RetryPolicy(1)
    )
    diagnostic = json.loads(response.diagnostics[0])

    assert "raw_response" not in diagnostic
    assert diagnostic["raw_response_size"] == 3000
    assert len(diagnostic["raw_response_excerpt"]) == 2000
    assert diagnostic["initial_raw_response_size"] == 7
    assert response.finish_reason == "length"
    assert response.usage == {"eval_count": 12}
