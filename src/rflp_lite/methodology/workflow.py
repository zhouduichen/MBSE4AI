"""Single durable orchestrator for all methodology TaskSpecs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.methodology.context import ContextBuilder
from rflp_lite.methodology.contracts import (
    Phase, RunStatus, StepStatus, TaskExecutionRequest, TaskExecutionResponse,
    TaskRuntime,
)
from rflp_lite.methodology.tasks import task_catalog, tasks_for_phase
from rflp_lite.methodology.gates import GateResult, gate_for_phase
from rflp_lite.repository.port import Run, RunRepository, Step


@dataclass(frozen=True, slots=True)
class RunSummary:
    run_id: str
    project_id: str
    phase: Phase
    status: RunStatus
    completed_tasks: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()


class WorkflowRunner:
    def __init__(self, model_repository, run_repository: RunRepository, runtime: TaskRuntime, context_builder: ContextBuilder | None = None, methodology_version: str = "v2.0"):
        self.model_repository = model_repository
        self.run_repository = run_repository
        self.runtime = runtime
        self.context_builder = context_builder or ContextBuilder()
        self.methodology_version = methodology_version

    def run(self, project_id: str, phase: Phase | None = None) -> RunSummary:
        selected_phase = phase or Phase.OPERATIONAL
        tasks = tasks_for_phase(selected_phase)
        if not tasks:
            raise ContractViolation(f"phase has no tasks: {selected_phase.value}")
        graph = self.model_repository.load_graph(project_id)
        run_id = f"run-{canonical_hash((project_id, selected_phase.value, graph.revision, self.methodology_version))[:16]}"
        run = Run(run_id, project_id, selected_phase.value, RunStatus.RUNNING.value, 0, self.methodology_version, "", graph.snapshot_hash, (), tuple(Step(run_id, task.id) for task in tasks))
        existing = self.run_repository.load_run(project_id, run_id)
        if existing is None:
            self.run_repository.create_run(run)
        completed: list[str] = []
        diagnostics: list[str] = []
        for task in tasks:
            current = self.model_repository.load_graph(project_id)
            context = self.context_builder.build(current, task)
            request = TaskExecutionRequest(task.id, self.methodology_version, context, context.evidence, {"schema_id": task.output_schema_id, "output_kinds": [kind.value for kind in task.output_kinds]}, 2000, task.tools)
            self.run_repository.update_step(Step(run_id, task.id, StepStatus.RUNNING.value, 1, current.snapshot_hash))
            try:
                response = self.runtime.execute(request)
                if response.patch is not None:
                    self.model_repository.append_patch(project_id, response.patch, current.revision)
                if response.status is StepStatus.COMPLETED:
                    completed.append(task.id)
                    self.run_repository.update_step(Step(run_id, task.id, response.status.value, 1, current.snapshot_hash, response.patch.id if response.patch else None, response.diagnostics))
                else:
                    diagnostics.extend(response.diagnostics)
                    self.run_repository.update_step(Step(run_id, task.id, response.status.value, 1, current.snapshot_hash, response.patch.id if response.patch else None, response.diagnostics))
            except Exception as exc:
                message = f"{task.id}: {exc}"
                diagnostics.append(message)
                self.run_repository.update_step(Step(run_id, task.id, StepStatus.DEGRADED.value, 1, current.snapshot_hash, None, (message,)))
        status = RunStatus.COMPLETED if len(completed) == len(tasks) else RunStatus.DEGRADED
        self._update_run_status(run_id, status, tuple(diagnostics))
        return RunSummary(run_id, project_id, selected_phase, status, tuple(completed), tuple(diagnostics))

    def resume(self, project_id: str, run_id: str) -> RunSummary:
        stored = self.run_repository.load_run(project_id, run_id)
        if stored is None:
            raise ContractViolation(f"run not found: {run_id}")
        phase = Phase(stored.phase)
        tasks = tasks_for_phase(phase)
        completed = {step.task_id for step in stored.steps if step.status == StepStatus.COMPLETED.value}
        result = self.run(project_id, phase)
        return RunSummary(result.run_id, result.project_id, result.phase, result.status, tuple(sorted(set(result.completed_tasks) | completed)), result.diagnostics)

    def repair(self, project_id: str, issue_id: str) -> RunSummary:
        raise ContractViolation(f"repair requires a registered issue: {issue_id}")

    def gate(self, project_id: str, phase: Phase) -> GateResult:
        return gate_for_phase(phase, self.model_repository.load_graph(project_id))

    def _update_run_status(self, run_id: str, status: RunStatus, diagnostics: tuple[str, ...]) -> None:
        updater = getattr(self.run_repository, "update_run", None)
        if updater is not None:
            updater(run_id, status.value, diagnostics)


class NoopRuntime:
    """Safe offline runtime used until a model profile is configured."""

    def execute(self, request: TaskExecutionRequest) -> TaskExecutionResponse:
        del request
        return TaskExecutionResponse(StepStatus.COMPLETED)
