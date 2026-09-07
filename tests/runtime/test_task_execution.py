from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.contracts import ContextBundle, StepStatus, TaskExecutionRequest
from rflp_lite.runtime.structured_model import StructuredModelRuntime
from rflp_lite.ports.generative_model import GenerationResponse


class FakeModel:
    def __init__(self, payload=None):
        self.request = None
        self.payload = payload or {"operations": []}

    def complete_json(self, request):
        self.request = request
        return GenerationResponse("task-1", self.payload, "input", "output", False, "fake", "fake-model")


def test_runtime_adapts_task_context_to_generation_request():
    model = FakeModel()
    runtime = StructuredModelRuntime(model)
    context = ContextBundle("p1", "task-1", 3, (make_entity(EntityKind.SYSTEM, "系统"),))

    result = runtime.execute(TaskExecutionRequest("task-1", "v2.0", context, (), {"type": "object"}, 100))

    assert result.status is StepStatus.COMPLETED
    assert model.request.lens_id == "task-1"
    assert model.request.user_payload["context"]["revision"] == 3


def test_runtime_turns_allowed_output_into_patch():
    model = FakeModel({
        "operations": [{"op": "ADD", "kind": "requirement", "name": "支持配送", "payload": {"source": "doc-1"}}],
        "reason": "从资料提取系统需求",
    })
    runtime = StructuredModelRuntime(model)
    context = ContextBundle("p1", "task-1", 3, (make_entity(EntityKind.SYSTEM, "系统"),))
    request = TaskExecutionRequest(
        "task-1", "v2.0", context, (),
        {"output_kinds": ["requirement"]}, 100,
    )

    result = runtime.execute(request)

    assert result.patch is not None
    assert result.patch.expected_revision == 3
    assert result.patch.operations[0].entity.kind is EntityKind.REQUIREMENT
