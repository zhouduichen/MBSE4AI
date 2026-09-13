import pytest

from rflp_lite.application.requirement_input import RequirementInputService
from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.errors import ConcurrentModificationError, ContractViolation
from rflp_lite.domain.model import AddEntity, Patch
from rflp_lite.methodology.contracts import FailureStage, Phase, RunStatus, StepStatus, TaskExecutionResponse
from rflp_lite.methodology.workflow import WorkflowRunner
from rflp_lite.repository.port import Step
from rflp_lite.methodology.tasks import tasks_for_phase
from rflp_lite.repository.sqlite import SQLiteModelRepository
from rflp_lite.runtime.rule_based import RuleRuntime


class FakeRuntime:
    def __init__(self):
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        return TaskExecutionResponse(StepStatus.COMPLETED)


class StructuralFailureRuntime:
    def execute(self, request):
        return TaskExecutionResponse(
            StepStatus.DEGRADED,
            diagnostics=("structured output rejected",),
            provider_id="ollama",
            model_id="qwen3.5:9b-q8_0",
            failure_stage=FailureStage.STRUCTURAL,
        )


class InvalidPatchResponseRuntime:
    def execute(self, request):
        entity = make_entity(EntityKind.SYSTEM, "不应提交")
        return TaskExecutionResponse(
            StepStatus.DEGRADED,
            patch=Patch.create(request.context_bundle.project_id, request.task_id, (AddEntity(entity),), "invalid", request.context_bundle.revision),
        )


class CommittableRuntime:
    def execute(self, request):
        entity = make_entity(EntityKind.SYSTEM, "候选系统")
        return TaskExecutionResponse(
            StepStatus.COMPLETED,
            Patch.create(
                request.context_bundle.project_id,
                request.task_id,
                (AddEntity(entity),),
                "测试 patch",
                request.context_bundle.revision,
            ),
        )


class RaisingAppendRepository(SQLiteModelRepository):
    def __init__(self, path, error):
        super().__init__(path)
        self.error = error

    def append_patch(self, project_id, patch, expected_revision, *, run_id=None):
        raise self.error


class DegradedSemanticRuntime:
    def __init__(self):
        self.delegate = RuleRuntime()

    def execute(self, request):
        if request.task_id == "functional_decomposition":
            return TaskExecutionResponse(
                StepStatus.COMPLETED,
                diagnostics=("offline:lifecycle-idempotent",),
            )
        return self.delegate.execute(request)


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
    assert len(runtime.requests) == len(tasks_for_phase(Phase.OPERATIONAL))
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


def test_structural_failure_stops_lifecycle_before_gate_repair(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    runner = WorkflowRunner(repository, repository, StructuralFailureRuntime())

    summary = runner.run("p1", force_run=True)
    stored = repository.load_run("p1", summary.run_id)

    assert summary.status is RunStatus.DEGRADED
    assert summary.failure_stage is FailureStage.STRUCTURAL
    assert stored is not None
    assert stored.status == RunStatus.DEGRADED.value
    assert all(step.repair_round == 0 for step in stored.steps)
    assert "semantic repair skipped" in " ".join(summary.diagnostics)


def test_degraded_phase_cannot_be_reported_as_completed_lifecycle(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    RequirementInputService(repository, "p1").ensure_text_requirements("系统应支持人工接管")
    runner = WorkflowRunner(repository, repository, DegradedSemanticRuntime())

    summary = runner.run("p1", force_run=True)

    assert summary.status is RunStatus.DEGRADED
    assert summary.phase is Phase.FUNCTIONAL
    assert summary.closure is not None
    assert summary.closure["status"] == "blocked"


def test_non_completed_patch_is_rejected_before_repository_append(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    runner = WorkflowRunner(repository, repository, InvalidPatchResponseRuntime())

    summary = runner.run("p1", Phase.OPERATIONAL, force_run=True)

    assert summary.status is RunStatus.DEGRADED
    assert repository.load_graph("p1").revision == 0
    stored = repository.load_run("p1", summary.run_id)
    assert stored is not None
    assert any("non-completed response" in item for item in stored.diagnostics)


@pytest.mark.parametrize(
    ("error", "stage", "diagnostic"),
    [
        (ContractViolation("contract broken"), FailureStage.INTERNAL, "contract_violation"),
        (RuntimeError("unexpected bug"), FailureStage.INTERNAL, "internal_error"),
    ],
)
def test_fail_closed_append_error_marks_failed_and_blocks_pending(tmp_path, error, stage, diagnostic):
    repository = RaisingAppendRepository(tmp_path / "model.db", error)
    repository.ensure_project("p1")
    runner = WorkflowRunner(repository, repository, CommittableRuntime())

    summary = runner.run("p1", Phase.OPERATIONAL, force_run=True)
    stored = repository.load_run("p1", summary.run_id)

    assert summary.failure_stage is stage
    assert stored is not None
    statuses = {step.task_id: step.status for step in stored.steps}
    assert statuses["system_definition"] == "failed"
    assert statuses["stakeholder_analysis"] == "blocked"
    assert repository.load_graph("p1").revision == 0
    assert diagnostic in " ".join(summary.diagnostics)


def test_workflow_invariant_fails_closed_before_repository_append(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    runner = WorkflowRunner(repository, repository, InvalidPatchResponseRuntime())

    summary = runner.run("p1", Phase.OPERATIONAL, force_run=True)
    stored = repository.load_run("p1", summary.run_id)

    assert summary.failure_stage is FailureStage.INTERNAL
    assert stored is not None
    statuses = {step.task_id: step.status for step in stored.steps}
    assert statuses["system_definition"] == "failed"
    assert statuses["stakeholder_analysis"] == "blocked"
    assert repository.load_graph("p1").revision == 0
    assert "workflow_invariant" in " ".join(summary.diagnostics)


def test_concurrent_modification_fails_closed_before_repository_mutation(tmp_path):
    repository = RaisingAppendRepository(
        tmp_path / "model.db",
        ConcurrentModificationError("stale ModelGraph revision"),
    )
    repository.ensure_project("p1")
    runner = WorkflowRunner(repository, repository, CommittableRuntime())

    summary = runner.run("p1", Phase.OPERATIONAL, force_run=True)
    stored = repository.load_run("p1", summary.run_id)

    assert summary.failure_stage is FailureStage.CONCURRENCY
    assert stored is not None
    statuses = {step.task_id: step.status for step in stored.steps}
    assert statuses["system_definition"] == "failed"
    assert statuses["stakeholder_analysis"] == "blocked"
    assert repository.load_graph("p1").revision == 0
    assert "concurrency_conflict" in " ".join(summary.diagnostics)


def test_structural_failure_marks_remaining_tasks_blocked(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    runner = WorkflowRunner(repository, repository, StructuralFailureRuntime())

    summary = runner.run("p1", Phase.OPERATIONAL, force_run=True)
    stored = repository.load_run("p1", summary.run_id)

    assert stored is not None
    statuses = {step.task_id: step.status for step in stored.steps}
    assert statuses["system_definition"] == "failed"
    assert statuses["stakeholder_analysis"] == "blocked"
