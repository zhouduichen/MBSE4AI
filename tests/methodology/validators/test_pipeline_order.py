from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import AddEntity, Patch
from rflp_lite.methodology.contracts import Phase, StepStatus, TaskExecutionResponse
from rflp_lite.methodology.workflow import WorkflowRunner
from rflp_lite.repository.sqlite import SQLiteModelRepository


class InvalidRuntime:
    def execute(self, request):
        return TaskExecutionResponse(
            StepStatus.COMPLETED,
            Patch.create(
                request.context_bundle.project_id,
                request.task_id,
                (AddEntity(make_entity(EntityKind.PHYSICAL_BLOCK, "越权实体")),),
                "invalid output",
                request.context_bundle.revision,
            ),
        )


def test_methodology_validation_happens_before_revision_append(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    runner = WorkflowRunner(repository, repository, InvalidRuntime())
    before = repository.load_graph("p1")

    summary = runner.run("p1", Phase.OPERATIONAL)
    after = repository.load_graph("p1")

    assert summary.status.value == "degraded"
    assert after.revision == before.revision == 0
    assert after.snapshot_hash == before.snapshot_hash
