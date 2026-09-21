from __future__ import annotations

import time

import pytest

from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.domain.model import AddEntity, ModelGraph, Patch
from rflp_lite.methodology.contracts import (
    ContextBundle,
    Phase,
    RunStatus,
    StepStatus,
    TaskExecutionResponse,
)
from rflp_lite.methodology.executor import TaskExecutor
from rflp_lite.methodology.tasks import task_catalog
from rflp_lite.methodology.workflow import WorkflowRunner
from rflp_lite.repository.port import Run
from rflp_lite.repository.sqlite import SQLiteModelRepository


class FeedbackRuntime:
    def __init__(self):
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        payload = {
            "method": "test",
            "verification_objective": "证明需求满足",
            "precondition": "系统上电",
            "test_condition": "执行接管任务",
            "input": "接管指令",
            "stimulus": "提交指令",
            "procedure": "执行并记录结果",
            "expected_result": "任务完成",
            "pass_criteria": "结果满足需求",
        }
        if len(self.requests) == 1:
            payload.pop("test_condition")
        entity = make_entity(EntityKind.VERIFICATION_CASE, "验证人工接管", payload)
        patch = Patch.create(
            request.context_bundle.project_id,
            request.task_id,
            (AddEntity(entity),),
            "verifier retry",
            request.context_bundle.revision,
        )
        return TaskExecutionResponse(StepStatus.COMPLETED, patch=patch)


def test_verifier_grounded_retry_discards_invalid_candidate_before_cas():
    task = next(item for item in task_catalog() if item.id == "verification_validation")
    requirement = make_entity(EntityKind.REQUIREMENT, "系统应支持人工接管", {"obligation": "系统应支持"})
    context = ContextBundle("p1", task.id, 0, (requirement,))
    runtime = FeedbackRuntime()

    response = TaskExecutor(runtime).execute(
        task,
        context,
        graph=ModelGraph("p1", (requirement,)),
    )

    assert response.status is StepStatus.COMPLETED
    assert response.patch is not None
    assert len(runtime.requests) == 2
    assert runtime.requests[0].validation_feedback == ()
    feedback = runtime.requests[1].validation_feedback[0]
    assert feedback.code == "semantic_invalid"
    assert feedback.retry_count == 1
    assert "test_condition" in feedback.actual


def test_expired_or_wrong_run_lease_blocks_cas(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    repository.create_run(Run("run-1", "p1", Phase.OPERATIONAL.value, RunStatus.RUNNING.value))
    now = time.time()

    assert repository.claim_run("p1", "run-1", "lease-a", now)
    assert not repository.claim_run("p1", "run-1", "lease-b", now)
    entity = make_entity(EntityKind.SYSTEM, "系统")
    patch = Patch.create("p1", "task", (AddEntity(entity),), "lease", 0)

    with pytest.raises(ContractViolation, match="lease"):
        repository.append_patch("p1", patch, 0, run_id="run-1", lease="lease-b")

    repository.release_run("p1", "run-1", "lease-a")
    with pytest.raises(ContractViolation, match="lease"):
        repository.append_patch("p1", patch, 0, run_id="run-1", lease="lease-a")


def test_completed_run_cannot_be_reclaimed(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    repository.create_run(Run("run-1", "p1", Phase.OPERATIONAL.value, RunStatus.COMPLETED.value))

    assert not repository.claim_run("p1", "run-1", "late-worker", time.time())


def test_workflow_claim_failure_returns_terminal_blocked_summary(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    repository.create_run(Run("run-1", "p1", Phase.OPERATIONAL.value, RunStatus.RUNNING.value))
    assert repository.claim_run("p1", "run-1", "other-worker", time.time())

    class Runtime:
        def execute(self, request):
            raise AssertionError("a worker without the lease must not execute")

    summary = WorkflowRunner(repository, repository, Runtime()).run(
        "p1", Phase.OPERATIONAL, run_id="run-1"
    )

    assert summary.status is RunStatus.BLOCKED
    assert summary.failure_stage.value == "concurrency"
    assert summary.diagnostics == ("concurrency:run_lease_unavailable",)
