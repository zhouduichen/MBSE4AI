from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.contracts import ContextBundle
from rflp_lite.methodology.context import ContextBuilder
from rflp_lite.methodology.executor import TaskExecutor
from rflp_lite.methodology.tasks import task_catalog
from rflp_lite.methodology.vertical_generation import stage_task
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
    assert all(item in model.requests[0].system_prompt for item in (
        "missing_requirement_ids", "canonical", "coverage gap",
    ))
    assert "decision_package" in model.requests[0].system_prompt
    assert "requirement_quality_coverage" in model.requests[0].system_prompt
    guidance = model.requests[0].user_payload["methodology_guidance"]
    assert guidance["version"] == "methodology-guidance.v1"
    assert guidance["task_id"] == task.id


def test_requirements_prompt_closes_a_single_missing_activity():
    model = CapturingModel()
    entities = tuple(
        make_entity(EntityKind(kind), kind)
        for kind in (
            "system", "stakeholder", "concern", "lifecycle_stage",
            "lifecycle_transition", "scenario_hypothesis", "use_case",
            "operational_scenario", "requirement",
        )
    )
    context = ContextBundle(
        "p1",
        "vertical.requirements",
        3,
        entities,
        methodology_guidance={
            "stage_completion": {
                "checks": [{"id": "activity_analysis", "passed": False}],
            },
        },
    )
    request = TaskExecutor(model).request(stage_task("requirements"), context, "v2.1")

    StructuredModelRuntime(model).execute(request)

    assert "Activity 是当前唯一的闭合缺口" in model.requests[0].system_prompt
    assert "normal、failure、alternative、boundary、exception" in model.requests[0].system_prompt


def test_logical_prompt_requires_typed_interface_and_state_ownership():
    model = CapturingModel()
    context = ContextBundle(
        "p1",
        "vertical.logical",
        3,
        (
            make_entity(EntityKind.REQUIREMENT, "系统应完成任务"),
            make_entity(EntityKind.FUNCTION, "执行任务"),
            make_entity(EntityKind.LOGICAL_COMPONENT, "任务控制"),
        ),
    )
    request = TaskExecutor(model).request(stage_task("logical"), context, "v2.1")

    StructuredModelRuntime(model).execute(request)

    prompt = model.requests[0].system_prompt
    assert "payload.owner_id" in prompt
    assert "payload.connected_component_ids" in prompt
