import json

from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import ModelGraph, UpdateEntity
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.domain.errors import StructuredOutputFailure
from rflp_lite.methodology.contracts import ContextBundle, StepStatus, TaskExecutionRequest
from rflp_lite.methodology.executor import TaskExecutor
from rflp_lite.methodology.registries import RetryPolicy
from rflp_lite.methodology.tasks import task_catalog
from rflp_lite.methodology.vertical_generation import stage_task
from rflp_lite.runtime.structured_model import StructuredModelRuntime
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
    assert (added.id, RelationPredicate.VERIFIED_BY, verification.id) in relations
    assert (added.id, RelationPredicate.VALIDATED_BY, validation.id) in relations


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
    relations = {
        (operation.source_id, operation.predicate, operation.target_id)
        for operation in response.patch.operations
        if hasattr(operation, "predicate")
    }
    assert all(
        (requirement.id, RelationPredicate.VALIDATED_BY, validation.id) in relations
        and (requirement.id, RelationPredicate.VERIFIED_BY, verification.id) in relations
        for requirement in requirements
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
