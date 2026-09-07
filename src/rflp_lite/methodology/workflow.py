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
from rflp_lite.methodology.tasks import output_contract, tasks_for_phase
from rflp_lite.methodology.gates import GateResult, gate_for_phase
from rflp_lite.methodology.coverage import CoverageGap, CoverageReport
from rflp_lite.methodology.repair import patch_for_plan, plan_repair
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

    def run(
        self,
        project_id: str,
        phase: Phase | None = None,
        *,
        run_id: str | None = None,
    ) -> RunSummary:
        selected_phase = phase or Phase.OPERATIONAL
        tasks = tasks_for_phase(selected_phase)
        if selected_phase is Phase.CLOSURE:
            graph = self.model_repository.load_graph(project_id)
            effective_run_id = run_id or f"run-{canonical_hash((project_id, selected_phase.value, graph.revision, self.methodology_version))[:16]}"
            if self.run_repository.load_run(project_id, effective_run_id) is None:
                self.run_repository.create_run(Run(effective_run_id, project_id, selected_phase.value, RunStatus.COMPLETED.value, 0, self.methodology_version, "", graph.snapshot_hash))
            else:
                self._update_run_status(effective_run_id, RunStatus.COMPLETED, ())
            return RunSummary(effective_run_id, project_id, selected_phase, RunStatus.COMPLETED)
        if not tasks:
            raise ContractViolation(f"phase has no tasks: {selected_phase.value}")
        graph = self.model_repository.load_graph(project_id)
        effective_run_id = run_id or f"run-{canonical_hash((project_id, selected_phase.value, graph.revision, self.methodology_version))[:16]}"
        existing = self.run_repository.load_run(project_id, effective_run_id)
        if existing is None:
            self.run_repository.create_run(
                Run(
                    effective_run_id,
                    project_id,
                    selected_phase.value,
                    RunStatus.RUNNING.value,
                    0,
                    self.methodology_version,
                    "",
                    graph.snapshot_hash,
                    (),
                    tuple(Step(effective_run_id, task.id) for task in tasks),
                )
            )
            existing = self.run_repository.load_run(project_id, effective_run_id)
        completed_before = {
            step.task_id for step in (existing.steps if existing else ())
            if step.status == StepStatus.COMPLETED.value
        }
        completed: list[str] = []
        diagnostics: list[str] = []
        for task in tasks:
            if task.id in completed_before:
                completed.append(task.id)
                continue
            current = self.model_repository.load_graph(project_id)
            context = self.context_builder.build(current, task)
            request = TaskExecutionRequest(
                task.id,
                self.methodology_version,
                context,
                context.evidence,
                output_contract(task) | {"schema_id": task.output_schema_id, "output_kinds": [kind.value for kind in task.output_kinds]},
                2000,
                task.tools,
            )
            prior_attempt = next(
                (step.attempt for step in (existing.steps if existing else ()) if step.task_id == task.id),
                0,
            )
            self.run_repository.update_step(
                Step(effective_run_id, task.id, StepStatus.RUNNING.value, prior_attempt + 1, current.snapshot_hash)
            )
            try:
                response = self.runtime.execute(request)
                if response.patch is not None:
                    self.model_repository.append_patch(project_id, response.patch, current.revision)
                if response.status is StepStatus.COMPLETED:
                    completed.append(task.id)
                    self.run_repository.update_step(
                        Step(effective_run_id, task.id, response.status.value, prior_attempt + 1, current.snapshot_hash, response.patch.id if response.patch else None, response.diagnostics)
                    )
                else:
                    diagnostics.extend(response.diagnostics)
                    self.run_repository.update_step(
                        Step(effective_run_id, task.id, response.status.value, prior_attempt + 1, current.snapshot_hash, response.patch.id if response.patch else None, response.diagnostics)
                    )
            except Exception as exc:
                message = f"{task.id}: {exc}"
                diagnostics.append(message)
                self.run_repository.update_step(
                    Step(effective_run_id, task.id, StepStatus.DEGRADED.value, prior_attempt + 1, current.snapshot_hash, None, (message,))
                )
        status = RunStatus.COMPLETED if len(completed) == len(tasks) else RunStatus.DEGRADED
        self._update_run_status(effective_run_id, status, tuple(diagnostics))
        return RunSummary(effective_run_id, project_id, selected_phase, status, tuple(completed), tuple(diagnostics))

    def resume(self, project_id: str, run_id: str) -> RunSummary:
        stored = self.run_repository.load_run(project_id, run_id)
        if stored is None:
            raise ContractViolation(f"run not found: {run_id}")
        phase = Phase(stored.phase)
        completed = {step.task_id for step in stored.steps if step.status == StepStatus.COMPLETED.value}
        result = self.run(project_id, phase, run_id=run_id)
        return RunSummary(result.run_id, result.project_id, result.phase, result.status, tuple(sorted(set(result.completed_tasks) | completed)), result.diagnostics)

    def repair(self, project_id: str, issue_id: str) -> RunSummary:
        issues = self.model_repository.list_issues(project_id)
        issue = next((item for item in issues if item.get("id") == issue_id), None)
        if issue is None:
            raise ContractViolation(f"repair requires a registered issue: {issue_id}")
        graph = self.model_repository.load_graph(project_id)
        code = str(issue.get("code", "issue"))
        root_cause = {
            "missing_stakeholder": "stakeholder",
            "missing_lifecycle": "lifecycle",
            "missing_scenario": "scenario",
            "missing_use_case": "scenario",
            "missing_requirement": "requirement",
            "missing_function": "function",
            "incomplete_rflp_chain": "architecture",
            "broken_requirement_rflp_trace": "architecture",
            "missing_verification": "verification",
        }.get(code, "evidence")
        plan = plan_repair(CoverageReport((CoverageGap(code, root_cause, tuple(str(item) for item in issue.get("entity_ids", ()))),)), revision=graph.revision)
        if not plan.operations:
            raise ContractViolation(f"issue has no automatic repair: {issue_id}")
        patch = patch_for_plan(project_id, f"repair.{code}", graph, plan)
        self.model_repository.append_patch(project_id, patch, graph.revision)
        return RunSummary(
            f"repair-{patch.id}", project_id, plan.rollback_phase,
            RunStatus.COMPLETED, (), (f"applied_patch={patch.id}",),
        )

    def gate(self, project_id: str, phase: Phase) -> GateResult:
        graph = self.model_repository.load_graph(project_id)
        result = gate_for_phase(phase, graph)
        saver = getattr(self.model_repository, "save_issue", None)
        if saver is not None:
            for gap in result.issues:
                issue_id = f"issue-{canonical_hash((project_id, result.gate_id, gap.code, graph.revision))[:16]}"
                saver(project_id, {
                    "id": issue_id,
                    "code": gap.code,
                    "severity": "error",
                    "entity_ids": list(gap.entity_ids),
                    "suggested_rollback": result.rollback_phase.value if result.rollback_phase else None,
                })
        return result

    def _update_run_status(self, run_id: str, status: RunStatus, diagnostics: tuple[str, ...]) -> None:
        updater = getattr(self.run_repository, "update_run", None)
        if updater is not None:
            updater(run_id, status.value, diagnostics)


class NoopRuntime:
    """Safe offline runtime used until a model profile is configured."""

    def execute(self, request: TaskExecutionRequest) -> TaskExecutionResponse:
        del request
        return TaskExecutionResponse(StepStatus.COMPLETED)
