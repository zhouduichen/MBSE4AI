import threading
import time
from types import SimpleNamespace

import pytest

from rflp_lite.application.requirement_input import RequirementInputService
from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.errors import ConcurrentModificationError, ContractViolation
from rflp_lite.domain.model import AddEntity, Patch, Relate
from rflp_lite.domain.relations import RelationPredicate
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


class InvalidLifecycleRelationRuntime:
    def __init__(self):
        self.delegate = RuleRuntime()

    def execute(self, request):
        if request.task_id == "use_case_analysis":
            stakeholder = next(
                item for item in request.context_bundle.entities
                if item.kind is EntityKind.STAKEHOLDER
            )
            use_case = make_entity(EntityKind.USE_CASE, "非法关系仍应保留的用例")
            patch = Patch.create(
                request.context_bundle.project_id,
                request.task_id,
                (
                    AddEntity(use_case),
                    Relate(
                        stakeholder.id,
                        RelationPredicate.PARTICIPATES_IN,
                        use_case.id,
                    ),
                ),
                "invalid lifecycle relation",
                request.context_bundle.revision,
            )
            return TaskExecutionResponse(StepStatus.COMPLETED, patch=patch)
        return self.delegate.execute(request)


class ParallelTrackingRuntime:
    supports_parallel_tasks = True

    def __init__(self):
        self.delegate = RuleRuntime()
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def execute(self, request):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.03)
            return self.delegate.execute(request)
        finally:
            with self._lock:
                self.active -= 1


class ConfiguredTransportRuntime:
    supports_parallel_tasks = True

    def execute(self, request):
        return TaskExecutionResponse(
            StepStatus.DEGRADED,
            diagnostics=(f"remote unavailable: {request.task_id}",),
            failure_stage=FailureStage.TRANSPORT,
        )


class TransportAfterUnenrichedInputRuntime:
    """Leave imported requirements sparse before exercising fallback recovery."""

    def __init__(self):
        self.delegate = RuleRuntime()

    def execute(self, request):
        if request.task_id == "stakeholder_requirements":
            return TaskExecutionResponse(
                StepStatus.COMPLETED,
                diagnostics=("remote proposal carried no requirement update",),
            )
        if request.task_id == "system_requirement_derivation":
            return TaskExecutionResponse(
                StepStatus.DEGRADED,
                diagnostics=("remote unavailable: system_requirement_derivation",),
                failure_stage=FailureStage.TRANSPORT,
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


def test_semantic_lifecycle_failure_recovers_with_typed_rule_patch(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    RequirementInputService(repository, "p1").ensure_text_requirements("系统应支持人工接管")
    runner = WorkflowRunner(repository, repository, InvalidLifecycleRelationRuntime())
    runner.runtime_selection = SimpleNamespace(
        mode="configured", profile_id="test-llm", provider_id="test", model_id="test"
    )

    summary = runner.run("p1", Phase.OPERATIONAL, force_run=True)

    graph = repository.load_graph("p1")
    stored = repository.load_run("p1", summary.run_id)
    assert summary.status is RunStatus.COMPLETED
    assert "use_case_analysis" in summary.completed_tasks
    assert "lifecycle:recovered_by_rule_runtime" in " ".join(summary.diagnostics)
    assert any(item.kind is EntityKind.USE_CASE for item in graph.entities)
    assert stored is not None
    use_case_step = next(step for step in stored.steps if step.task_id == "use_case_analysis")
    assert use_case_step.status == StepStatus.COMPLETED.value
    assert use_case_step.repair_strategy == "rule_runtime_fallback"


def test_configured_runtime_parallelizes_dependency_safe_task_group(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    RequirementInputService(repository, "p1").ensure_text_requirements("系统应支持人工接管")
    runtime = ParallelTrackingRuntime()
    runner = WorkflowRunner(repository, repository, runtime)
    runner.runtime_selection = SimpleNamespace(
        mode="configured", profile_id="test-llm", provider_id="test", model_id="test"
    )

    summary = runner.run("p1", Phase.FUNCTIONAL, force_run=True)

    assert summary.status is RunStatus.COMPLETED
    assert runtime.max_active >= 2


def test_configured_transport_gap_recovers_complete_lifecycle(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    RequirementInputService(repository, "p1").ensure_text_requirements("系统应支持人工接管")
    runner = WorkflowRunner(repository, repository, ConfiguredTransportRuntime())
    runner.runtime_selection = SimpleNamespace(
        mode="configured", profile_id="test-llm", provider_id="test", model_id="test"
    )

    summary = runner.run("p1", force_run=True)

    assert summary.status is RunStatus.COMPLETED
    assert len(summary.completed_tasks) == 23
    assert "lifecycle:recovered_by_rule_runtime" in " ".join(summary.diagnostics)
    assert repository.load_graph("p1").relations


def test_lifecycle_fallback_enriches_sparse_imported_requirement(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "无人机飞行时间约束",
        {"fixture_id": "drone-endurance", "verification_method": "test"},
    )
    repository.append_patch(
        "p1",
        Patch.create("p1", "seed", (AddEntity(requirement),), "seed", 0),
        0,
    )
    runtime = TransportAfterUnenrichedInputRuntime()
    runner = WorkflowRunner(repository, repository, runtime)
    runner.runtime_selection = SimpleNamespace(
        mode="configured", profile_id="test-llm", provider_id="test", model_id="test"
    )

    summary = runner.run("p1", Phase.OPERATIONAL, force_run=True)

    assert summary.status is RunStatus.COMPLETED
    updated = repository.load_graph("p1").entity_index[requirement.id]
    assert updated.payload["obligation"] == "系统应"
    assert "lifecycle:recovered_by_rule_runtime" in " ".join(summary.diagnostics)


def test_lifecycle_transport_fallback_recovers_hardware_named_requirement(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    RequirementInputService(repository, "p1").ensure_text_requirements(
        "无人机系统通信链路应稳定，支持高清视频与传感器数据回传"
    )
    runner = WorkflowRunner(repository, repository, ConfiguredTransportRuntime())
    runner.runtime_selection = SimpleNamespace(
        mode="configured", profile_id="test-llm", provider_id="test", model_id="test"
    )

    summary = runner.run("p1", force_run=True)

    assert summary.status is RunStatus.COMPLETED
    functions = [
        item for item in repository.load_graph("p1").entities
        if item.kind is EntityKind.FUNCTION
    ]
    assert functions
    assert all("传感器" not in item.meta.name for item in functions)
    assert "传感器" in functions[0].payload["behavior"]


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
