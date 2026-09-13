import json

from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import ModelGraph, UpdateEntity
from rflp_lite.domain.errors import StructuredOutputFailure
from rflp_lite.methodology.contracts import ContextBundle, StepStatus, TaskExecutionRequest
from rflp_lite.methodology.executor import TaskExecutor
from rflp_lite.methodology.registries import RetryPolicy
from rflp_lite.methodology.tasks import task_catalog
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


def test_runtime_returns_stage_review_metadata():
    model = FakeModel({
        "entities": [], "relations": [], "updates": [], "deprecations": [],
        "reason": "补充阶段假设",
        "assumptions": ["校园网络可用"],
        "open_questions": ["是否允许夜间配送"],
    })
    runtime = StructuredModelRuntime(model)
    task = task_catalog()[1]
    context = ContextBundle("p1", task.id, 3, (make_entity(EntityKind.SYSTEM, "系统"),))

    result = runtime.execute(TaskExecutor(model).request(task, context, "v2.0"))

    assert result.assumptions == ("校园网络可用",)
    assert result.open_questions == ("是否允许夜间配送",)


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
