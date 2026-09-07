from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import AddEntity, Patch
from rflp_lite.methodology.contracts import Phase, StepStatus, TaskExecutionResponse
from rflp_lite.methodology.workflow import WorkflowRunner
from rflp_lite.repository.port import RunRepository, Step
from rflp_lite.repository.sqlite import SQLiteModelRepository


class FakeRuntime:
    def __init__(self):
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        return TaskExecutionResponse(StepStatus.COMPLETED)


def test_runner_persists_steps_and_completes_offline(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    repository.append_patch(
        "p1",
        Patch.create("p1", "seed", (AddEntity(make_entity(EntityKind.SYSTEM, "系统")),), "seed", 0),
        0,
    )
    runtime = FakeRuntime()
    runner = WorkflowRunner(repository, repository, runtime)

    summary = runner.run("p1", Phase.OPERATIONAL)
    stored = repository.load_run("p1", summary.run_id)

    assert summary.status.value == "completed"
    assert len(runtime.requests) == 4
    assert stored is not None
    assert all(step.status == "completed" for step in stored.steps)


def test_context_does_not_include_physical_entities_for_functional_task(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    repository.append_patch(
        "p1",
        Patch.create(
            "p1", "seed", (
                AddEntity(make_entity(EntityKind.FUNCTION, "配送")),
                AddEntity(make_entity(EntityKind.PHYSICAL_BLOCK, "传感器")),
            ), "seed", 0,
        ),
        0,
    )
    runtime = FakeRuntime()
    runner = WorkflowRunner(repository, repository, runtime)

    runner.run("p1", Phase.FUNCTIONAL)

    assert all(entity.kind is not EntityKind.PHYSICAL_BLOCK for entity in runtime.requests[0].context_bundle.entities)
