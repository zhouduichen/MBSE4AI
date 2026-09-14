from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.context import ContextBuilder
from rflp_lite.methodology.executor import TaskExecutor
from rflp_lite.methodology.tasks import task_catalog
from rflp_lite.ports.generative_model import GenerationResponse
from rflp_lite.runtime.structured_model import StructuredModelRuntime


class CapturingModel:
    def __init__(self):
        self.requests = []

    def complete_json(self, request):
        self.requests.append(request)
        return GenerationResponse(
            request.lens_id,
            {"entities": [], "relations": [], "updates": [], "deprecations": [], "reason": "无变化"},
            "input", "output", False,
        )


def test_structured_runtime_sends_task_specific_prompt_to_model():
    model = CapturingModel()
    task = task_catalog()[1]
    context = ContextBuilder().build(ModelGraph("p1"), task)
    request = TaskExecutor(model).request(task, context, "v2.1")

    StructuredModelRuntime(model).execute(request)

    assert request.prompt_text in model.requests[0].system_prompt
    assert all(item in model.requests[0].system_prompt for item in (
        "entities", "relations", "updates", "deprecations", "reason", "local_ref",
    ))
    guidance = model.requests[0].user_payload["methodology_guidance"]
    assert guidance["version"] == "methodology-guidance.v1"
    assert guidance["task_id"] == task.id
