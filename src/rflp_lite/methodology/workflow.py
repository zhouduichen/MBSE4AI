"""Task execution and the single durable methodology lifecycle."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from concurrent.futures import ThreadPoolExecutor
import time
from uuid import uuid4

from rflp_lite.application.closure_service import ClosureService
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import (
    ConcurrentModificationError,
    ContractViolation,
    MethodologyValidationError,
    WorkflowInvariantError,
)
from rflp_lite.domain.entities import EntityStatus, Producer
from rflp_lite.domain.model import AddEntity, Deprecate, Patch, Relate, UpdateEntity
from rflp_lite.methodology.context import ContextBuilder
from rflp_lite.methodology.completion import evaluate_completion
from rflp_lite.methodology.contracts import ContextBundle, FailureStage, Phase, RunStatus, StepStatus, TaskExecutionResponse, TaskRuntime
from rflp_lite.methodology.coverage import CoverageGap, CoverageReport
from rflp_lite.methodology.architecture_persistence import enrich_architecture_patch
from rflp_lite.methodology.executor import TaskExecutor
from rflp_lite.methodology.gates import GateResult, gate_for_phase
from rflp_lite.methodology.identity import RunIdentity
from rflp_lite.methodology.repair import patch_for_plan, plan_repair
from rflp_lite.methodology.repair_context import build_repair_context
from rflp_lite.methodology.repair_planner import plan as plan_repair_task
from rflp_lite.methodology.repair_strategies import LLMRepairStrategy, RuleFallbackRepairStrategy
from rflp_lite.methodology.tasks import task_catalog, task_spec_hash, tasks_for_phase
from rflp_lite.runtime.lifecycle_rule import LIFECYCLE_TASKS, LifecycleTaskRuleRuntime
from rflp_lite.repository.port import Run, RunRepository, Step
from rflp_lite.retrieval.evidence import RetrievalEngine


_NON_SEMANTIC_FAILURE_STAGES = frozenset({
    FailureStage.STRUCTURAL,
    FailureStage.COMPILER,
    FailureStage.TRANSPORT,
    FailureStage.CONCURRENCY,
    FailureStage.INTERNAL,
})


# These are dependency-safe only after the preceding group has committed its
# snapshot.  The order inside a group is the deterministic merge order; the
# provider calls themselves may run concurrently.
_PARALLEL_PHASE_GROUPS = {
    Phase.OPERATIONAL: (
        ("system_definition",),
        ("stakeholder_analysis", "lifecycle_analysis"),
        ("stakeholder_requirements", "scenario_exploration"),
        ("use_case_analysis",),
        ("operational_scenario",),
        ("activity_analysis",),
        ("system_requirement_derivation",),
    ),
    Phase.FUNCTIONAL: (
        ("function_identification",),
        (
            "functional_decomposition",
            "functional_interaction",
            "functional_scenario",
            "functional_requirement",
        ),
    ),
    Phase.LOGICAL_PHYSICAL: (
        ("logical_analysis",),
        ("physical_candidates",),
        ("allocation_tradeoff",),
        ("technical_requirement",),
    ),
    Phase.ASSURANCE: (
        (
            "interface_sequence_state",
            "fmea_stpa_hazard",
            "verification_validation",
        ),
        ("reverse_feasibility",),
        ("global_cross_analysis",),
    ),
}


@dataclass(frozen=True, slots=True)
class RunSummary:
    run_id: str
    project_id: str
    phase: Phase
    status: RunStatus
    completed_tasks: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    gate_id: str = ""
    gate_passed: bool | None = None
    phase_results: tuple[dict[str, object], ...] = ()
    gate_results: tuple[dict[str, object], ...] = ()
    closure: dict[str, object] | None = None
    failure_stage: FailureStage | None = None


@dataclass(frozen=True, slots=True)
class _PreparedParallelTask:
    current: object
    context: ContextBundle
    request: object
    prior_attempt: int
    started: float
    future: object


@dataclass(frozen=True, slots=True)
class _TaskRunResult:
    completed: bool
    diagnostics: tuple[str, ...] = ()
    failure_stage: FailureStage | None = None


class LifecycleOrchestrator:
    """Operational → Functional → Logical/Physical → Assurance → Closure."""

    phases = (Phase.OPERATIONAL, Phase.FUNCTIONAL, Phase.LOGICAL_PHYSICAL, Phase.ASSURANCE)

    def __init__(self, runner: "WorkflowRunner"):
        self.runner = runner

    def run(
        self,
        project_id: str,
        *,
        run_id: str | None = None,
        force_new: bool = False,
        max_repair_rounds: int = 2,
    ) -> RunSummary:
        identity = self.runner._ensure_run(project_id, run_id=run_id, force_new=force_new)
        diagnostics: list[str] = []
        gate_snapshot: list[dict[str, object]] = []
        phase_results: list[dict[str, object]] = []
        completed: list[str] = []
        stalled_fingerprints: dict[tuple[object, ...], int] = {}
        for phase in self.phases:
            phase_summary = self.runner._run_phase(project_id, phase, run_id=identity.run_id)
            phase_results.append({"phase": phase.value, "status": phase_summary.status.value, "completed_tasks": list(phase_summary.completed_tasks), "diagnostics": list(phase_summary.diagnostics)})
            completed.extend(phase_summary.completed_tasks)
            diagnostics.extend(phase_summary.diagnostics)
            if phase_summary.status is not RunStatus.COMPLETED:
                failure_reason = (
                    phase_summary.failure_stage.value
                    if phase_summary.failure_stage is not None
                    else "semantic"
                )
                if phase_summary.failure_stage in _NON_SEMANTIC_FAILURE_STAGES:
                    diagnostics.append(f"{phase.value}: {failure_reason} failure; semantic repair skipped")
                self.runner._block_pending_steps(
                    project_id,
                    identity.run_id,
                    f"blocked by {phase.value} {failure_reason} failure",
                )
                self.runner._update_run_status(identity.run_id, RunStatus.DEGRADED, tuple(diagnostics))
                completed_phases = {item["phase"] for item in phase_results}
                for pending in self.phases:
                    if pending.value not in completed_phases:
                        phase_results.append({"phase": pending.value, "status": StepStatus.BLOCKED.value, "completed_tasks": [], "diagnostics": [f"Blocked by {failure_reason} failure"]})
                phase_results.append({"phase": Phase.CLOSURE.value, "status": "blocked", "completed_tasks": [], "diagnostics": [f"{failure_reason} failure must be resolved before Closure"]})
                return RunSummary(
                    identity.run_id, project_id, phase, RunStatus.DEGRADED,
                    tuple(dict.fromkeys(completed)), tuple(diagnostics), "", False,
                    tuple(phase_results), tuple(gate_snapshot),
                    {"status": "blocked", "accepted_revision": None, "manifest": None},
                    phase_summary.failure_stage,
                )
            gate = self.runner.gate(project_id, phase, run_id=identity.run_id)
            gate_snapshot.append(self.runner._gate_payload(gate, phase))
            for repair_round in range(max(0, max_repair_rounds) + 1):
                if gate.passed:
                    break
                if repair_round >= max_repair_rounds:
                    message = f"{phase.value}: {gate.gate_id} failed after targeted repair"
                    diagnostics.append(message)
                    self.runner._update_run_status(identity.run_id, RunStatus.DEGRADED, tuple(diagnostics))
                    completed_phases = {item["phase"] for item in phase_results}
                    for pending in self.phases:
                        if pending.value not in completed_phases:
                            phase_results.append({"phase": pending.value, "status": "pending", "completed_tasks": [], "diagnostics": []})
                    phase_results.append({"phase": Phase.CLOSURE.value, "status": "blocked", "completed_tasks": [], "diagnostics": ["Global Gate must pass before Closure"]})
                    return RunSummary(identity.run_id, project_id, phase, RunStatus.DEGRADED, tuple(dict.fromkeys(completed)), tuple(diagnostics), gate.gate_id, False, tuple(phase_results), tuple(gate_snapshot), {"status": "blocked", "accepted_revision": None, "manifest": None})
                self.runner._update_run_status(identity.run_id, RunStatus.REPAIRING, tuple(diagnostics))
                before_graph = self.runner.model_repository.load_graph(project_id)
                before_gap = tuple(sorted((item.code, item.entity_ids) for item in gate.issues))
                for issue in gate.issues:
                    issue_id = self.runner._issue_id(project_id, gate, issue)
                    try:
                        repaired = self.runner.repair(project_id, issue_id, run_id=identity.run_id, repair_round=repair_round + 1)
                        diagnostics.extend(repaired.diagnostics)
                    except ContractViolation as exc:
                        diagnostics.append(f"repair {issue.code}: {exc}")
                    target = self.runner._target_task_for_issue(issue.code)
                    if target:
                        rerun = self.runner._run_phase(project_id, phase, run_id=identity.run_id, rerun_task_ids={target})
                        completed.extend(rerun.completed_tasks)
                        diagnostics.extend(rerun.diagnostics)
                gate = self.runner.gate(project_id, phase, run_id=identity.run_id)
                gate_snapshot.append(self.runner._gate_payload(gate, phase))
                if not gate.passed:
                    after_graph = self.runner.model_repository.load_graph(project_id)
                    after_gap = tuple(sorted((item.code, item.entity_ids) for item in gate.issues))
                    if after_graph.snapshot_hash == before_graph.snapshot_hash or after_gap == before_gap:
                        fingerprint = (phase.value, before_gap, after_gap)
                        stalled_fingerprints[fingerprint] = stalled_fingerprints.get(fingerprint, 0) + 1
                        if stalled_fingerprints[fingerprint] >= 2:
                            diagnostics.append(f"repair_stalled: {phase.value}")
                            self.runner._update_run_status(identity.run_id, RunStatus.DEGRADED, tuple(diagnostics))
                            break
            if not gate.passed:
                message = f"{phase.value}: {gate.gate_id} failed after targeted repair"
                diagnostics.append(message)
                self.runner._update_run_status(identity.run_id, RunStatus.DEGRADED, tuple(diagnostics))
                completed_phases = {item["phase"] for item in phase_results}
                for pending in self.phases:
                    if pending.value not in completed_phases:
                        phase_results.append({"phase": pending.value, "status": "pending", "completed_tasks": [], "diagnostics": []})
                phase_results.append({"phase": Phase.CLOSURE.value, "status": "blocked", "completed_tasks": [], "diagnostics": ["Global Gate must pass before Closure"]})
                return RunSummary(identity.run_id, project_id, phase, RunStatus.DEGRADED, tuple(dict.fromkeys(completed)), tuple(diagnostics), gate.gate_id, False, tuple(phase_results), tuple(gate_snapshot), {"status": "blocked", "accepted_revision": None, "manifest": None})
        closure = self.runner.closure.close(project_id, identity.run_id, gate_snapshot=tuple(gate_snapshot))
        diagnostics.append(f"closure_revision={closure.revision}")
        self.runner._update_run_status(identity.run_id, RunStatus.COMPLETED, tuple(diagnostics))
        phase_results.append({"phase": Phase.CLOSURE.value, "status": RunStatus.COMPLETED.value, "completed_tasks": [], "diagnostics": []})
        return RunSummary(identity.run_id, project_id, Phase.CLOSURE, RunStatus.COMPLETED, tuple(dict.fromkeys(completed)), tuple(diagnostics), "Global-Gate", True, tuple(phase_results), tuple(gate_snapshot), closure.as_dict())


class WorkflowRunner:
    def __init__(
        self,
        model_repository,
        run_repository: RunRepository,
        runtime: TaskRuntime,
        context_builder: ContextBuilder | None = None,
        methodology_version: str = "v2.1",
        *,
        runtime_selection=None,
    ):
        self.model_repository = model_repository
        self.run_repository = run_repository
        self.runtime = runtime
        self.runtime_selection = runtime_selection
        self.context_builder = context_builder or ContextBuilder(RetrievalEngine(model_repository))
        self.methodology_version = methodology_version
        self.executor = TaskExecutor(runtime)
        self.closure = ClosureService(model_repository)
        self.orchestrator = LifecycleOrchestrator(self)
        self._leases: dict[str, str] = {}
        self._parallel_executor: ThreadPoolExecutor | None = None
        self._lifecycle_fallback_executor = TaskExecutor(
            LifecycleTaskRuleRuntime(),
            prompt_registry=self.executor.prompts,
            schema_registry=self.executor.schemas,
            validator_registry=self.executor.validators,
        )

    def run(
        self,
        project_id: str,
        phase: Phase | None = None,
        *,
        run_id: str | None = None,
        force_new: bool = False,
        new_run: bool = False,
        force_run: bool = False,
    ) -> RunSummary:
        if phase is None:
            return self.orchestrator.run(project_id, run_id=run_id, force_new=force_new or new_run or force_run)
        if phase is Phase.CLOSURE:
            identity = self._ensure_run(project_id, run_id=run_id, force_new=force_new or new_run or force_run)
            closure = self.closure.close(project_id, identity.run_id)
            self._update_run_status(identity.run_id, RunStatus.COMPLETED, (f"closure_revision={closure.revision}",))
            return RunSummary(identity.run_id, project_id, Phase.CLOSURE, RunStatus.COMPLETED)
        return self._run_phase(project_id, phase, run_id=run_id, force_new=force_new or new_run or force_run)

    def _run_phase(self, project_id: str, phase: Phase, *, run_id: str | None = None, force_new: bool = False, rerun_task_ids: set[str] | None = None) -> RunSummary:
        tasks = tasks_for_phase(phase)
        if not tasks:
            raise ContractViolation(f"phase has no tasks: {phase.value}")
        identity = self._ensure_run(project_id, run_id=run_id, force_new=force_new, phase=phase, tasks=tasks)
        existing = self.run_repository.load_run(project_id, identity.run_id)
        task_ids = {task.id for task in tasks}
        completed_before = {
            step.task_id
            for step in (existing.steps if existing else ())
            if step.task_id in task_ids and step.status == StepStatus.COMPLETED.value
        }
        completed = set(completed_before)
        diagnostics: list[str] = []
        prefetched: dict[str, _PreparedParallelTask] = {}
        task_schedule = _execution_schedule(
            phase,
            tasks,
            parallel_enabled=self._parallel_tasks_enabled(),
        )
        parallel_groups = _parallel_groups_by_first_task(phase, task_schedule)
        for task in task_schedule:
            group = parallel_groups.get(task.id)
            if group and not prefetched and self._parallel_tasks_enabled():
                prefetched.update(
                    self._prepare_parallel_tasks(
                        project_id,
                        identity.run_id,
                        group,
                        completed_before,
                        rerun_task_ids,
                        existing,
                    )
                )
            if task.id in completed_before and (rerun_task_ids is None or task.id not in rerun_task_ids):
                continue
            result = self._run_phase_task(
                project_id,
                phase,
                identity,
                task,
                existing,
                prefetched.pop(task.id, None),
                completed,
                diagnostics,
            )
            diagnostics.extend(result.diagnostics)
            if result.completed:
                completed.add(task.id)
            if result.failure_stage is not None:
                return RunSummary(
                    identity.run_id,
                    project_id,
                    phase,
                    RunStatus.DEGRADED,
                    tuple(sorted(completed)),
                    tuple(diagnostics),
                    failure_stage=result.failure_stage,
                )
        status = RunStatus.COMPLETED if len(completed) == len(tasks) else RunStatus.DEGRADED
        self._update_run_status(identity.run_id, status, tuple(diagnostics))
        return RunSummary(identity.run_id, project_id, phase, status, tuple(sorted(completed)), tuple(diagnostics))

    def _run_phase_task(
        self,
        project_id: str,
        phase: Phase,
        identity: RunIdentity,
        task,
        existing,
        prepared: _PreparedParallelTask | None,
        completed: set[str],
        diagnostics: list[str],
    ) -> _TaskRunResult:
        if prepared is None:
            current, context, request, prior_attempt, started = self._prepare_task(
                project_id, identity.run_id, task, existing
            )
        else:
            current = self.model_repository.load_graph(project_id)
            context = prepared.context
            request = prepared.request
            prior_attempt = prepared.prior_attempt
            started = prepared.started
        context_hash = canonical_hash(context)
        try:
            response = (
                prepared.future.result()
                if prepared is not None
                else self.executor.execute(
                    task,
                    context,
                    self.methodology_version,
                    token_budget=self._output_budget(),
                    )
                )
            if prepared is not None and response.patch is not None:
                rebased = _rebase_parallel_patch(
                    project_id, task.id, response.patch, current
                )
                response = replace(
                    response,
                    patch=rebased,
                    output_hash=canonical_hash(rebased),
                )
            return self._accept_task_response(
                project_id,
                identity.run_id,
                task,
                current,
                context,
                request,
                prior_attempt,
                started,
                response,
                diagnostics,
            )
        except MethodologyValidationError as exc:
            message = f"{task.id}: semantic validation: {exc}"
            recovered = self._recover_lifecycle_task(
                project_id,
                identity.run_id,
                task,
                current,
                context,
                request,
                prior_attempt,
                started,
                message,
            )
            if recovered is not None:
                return _TaskRunResult(*recovered)
            self.run_repository.update_step(
                self._step_record(
                    identity.run_id,
                    task,
                    StepStatus.DEGRADED,
                    prior_attempt,
                    context_hash,
                    None,
                    (message,),
                    "",
                    request,
                    started,
                )
            )
            return _TaskRunResult(False, (message,))
        except ConcurrentModificationError as exc:
            return self._fail_closed_task(
                project_id, phase, identity, task, request, context_hash,
                prior_attempt, started, completed, diagnostics, FailureStage.CONCURRENCY,
                "concurrency_conflict", exc,
            )
        except WorkflowInvariantError as exc:
            return self._fail_closed_task(
                project_id, phase, identity, task, request, context_hash,
                prior_attempt, started, completed, diagnostics, FailureStage.INTERNAL,
                "workflow_invariant", exc,
            )
        except ContractViolation as exc:
            return self._fail_closed_task(
                project_id, phase, identity, task, request, context_hash,
                prior_attempt, started, completed, diagnostics, FailureStage.INTERNAL,
                "contract_violation", exc,
            )
        except Exception as exc:
            return self._fail_closed_task(
                project_id, phase, identity, task, request, context_hash,
                prior_attempt, started, completed, diagnostics, FailureStage.INTERNAL,
                "internal_error", exc,
            )

    def _accept_task_response(
        self,
        project_id: str,
        run_id: str,
        task,
        current,
        context,
        request,
        prior_attempt: int,
        started: float,
        response,
        diagnostics: list[str],
    ) -> _TaskRunResult:
        if response.patch is not None:
            response = replace(
                response,
                patch=enrich_architecture_patch(current, response.patch),
            )
        if response.patch is not None and response.status is not StepStatus.COMPLETED:
            raise WorkflowInvariantError(
                "non-completed response cannot carry a committable patch"
            )
        if response.status is StepStatus.COMPLETED:
            self.executor.validate_response(project_id, task, current, context, response)
        patch_id = None
        revision = current
        if response.patch is not None:
            revision = self.model_repository.append_patch(
                project_id,
                response.patch,
                current.revision,
                run_id=run_id,
            )
            patch_id = response.patch.id
            patch_trace = getattr(self.model_repository, "update_patch_trace", None)
            if patch_trace is not None:
                patch_trace(
                    patch_id,
                    provider_id=response.provider_id or self._provider_id(),
                    model_id=response.model_id or self._model_id(),
                )
            self._record_audit(
                project_id,
                "task.patch",
                {
                    "run_id": run_id,
                    "task_id": task.id,
                    "patch_id": patch_id,
                    "revision": revision.sequence,
                    "input_hash": response.input_hash,
                    "output_hash": response.output_hash,
                },
            )
        if response.failure_stage in _NON_SEMANTIC_FAILURE_STAGES:
            recovered = self._recover_lifecycle_task(
                project_id,
                run_id,
                task,
                current,
                context,
                request,
                prior_attempt,
                started,
                f"{task.id}: {response.failure_stage.value} failure",
            )
            if recovered is not None:
                return _TaskRunResult(*recovered)
            self.run_repository.update_step(
                self._step_record(
                    run_id,
                    task,
                    StepStatus.FAILED,
                    prior_attempt,
                    response.input_hash or canonical_hash(context),
                    patch_id,
                    response.diagnostics,
                    response.output_hash,
                    request,
                    started,
                )
            )
            self._block_pending_steps(
                project_id,
                run_id,
                f"blocked by {task.id} {response.failure_stage.value} failure",
                after_task_id=task.id,
            )
            return _TaskRunResult(False, response.diagnostics, response.failure_stage)
        completion = evaluate_completion(
            task, self.model_repository.load_graph(project_id), response
        )
        if completion.passed and response.patch is not None:
            self._promote_completed_output(
                project_id,
                run_id,
                response.patch,
                revision.sequence,
            )
        if not completion.passed:
            response = replace(
                response,
                status=StepStatus.DEGRADED,
                diagnostics=tuple(response.diagnostics) + completion.issue_codes,
            )
        self.run_repository.update_step(
            self._step_record(
                run_id,
                task,
                response.status,
                prior_attempt,
                response.input_hash or canonical_hash(context),
                patch_id,
                response.diagnostics,
                response.output_hash,
                request,
                started,
            )
        )
        return _TaskRunResult(response.status is StepStatus.COMPLETED, response.diagnostics)

    def _step_record(
        self,
        run_id: str,
        task,
        status: StepStatus,
        prior_attempt: int,
        input_hash: str,
        patch_id: str | None,
        diagnostics,
        output_hash: str,
        request,
        started: float,
        *,
        provider_id: str | None = None,
        model_id: str | None = None,
        repair_strategy: str = "none",
    ) -> Step:
        return Step(
            run_id,
            task.id,
            status.value,
            prior_attempt + 1,
            input_hash,
            patch_id,
            tuple(diagnostics),
            output_hash,
            provider_id or self._provider_id(),
            model_id or self._model_id(),
            task.prompt_template_id,
            input_hash,
            started,
            time.time(),
            request.prompt_version,
            request.prompt_hash,
            task_spec_hash(task),
            repair_strategy,
            0,
        )

    def _prepare_task(self, project_id: str, run_id: str, task, existing):
        current = self.model_repository.load_graph(project_id)
        context = self.context_builder.build(
            current,
            task,
            token_budget=self._context_budget(),
            output_reserve=self._output_budget() if self._configured_output_budget() else None,
            prompt_reserve=256,
        )
        request = self.executor.request(
            task,
            context,
            self.methodology_version,
            token_budget=self._output_budget(),
        )
        prior_attempt = next(
            (
                step.attempt
                for step in (existing.steps if existing else ())
                if step.task_id == task.id
            ),
            0,
        )
        started = time.time()
        context_hash = canonical_hash(context)
        self.run_repository.update_step(
            Step(
                run_id,
                task.id,
                StepStatus.RUNNING.value,
                prior_attempt + 1,
                context_hash,
                None,
                (),
                "",
                self._provider_id(),
                self._model_id(),
                task.prompt_template_id,
                context_hash,
                started,
                0.0,
                request.prompt_version,
                request.prompt_hash,
                task_spec_hash(task),
                "none",
                0,
            )
        )
        return current, context, request, prior_attempt, started

    def _parallel_tasks_enabled(self) -> bool:
        """Use task-level concurrency only for a configured capable provider."""

        if self._mode() != "configured":
            return False
        model = getattr(self.runtime, "model", None)
        return bool(
            getattr(self.runtime, "supports_parallel_tasks", False)
            or getattr(model, "supports_parallel_requirement_batching", False)
        )

    def _prepare_parallel_tasks(
        self,
        project_id: str,
        run_id: str,
        tasks,
        completed_before: set[str],
        rerun_task_ids: set[str] | None,
        existing,
    ) -> dict[str, _PreparedParallelTask]:
        """Prepare one dependency-safe snapshot and dispatch its LLM calls."""

        pending = tuple(
            task for task in tasks
            if task.id not in completed_before
            or (rerun_task_ids is not None and task.id in rerun_task_ids)
        )
        if len(pending) < 2:
            return {}
        current = self.model_repository.load_graph(project_id)
        prepared: dict[str, _PreparedParallelTask] = {}
        for task in pending:
            context = self.context_builder.build(
                current,
                task,
                token_budget=self._context_budget(),
                output_reserve=self._output_budget() if self._configured_output_budget() else None,
                prompt_reserve=256,
            )
            request = self.executor.request(
                task,
                context,
                self.methodology_version,
                token_budget=self._output_budget(),
            )
            prior_attempt = next(
                (
                    step.attempt
                    for step in (existing.steps if existing else ())
                    if step.task_id == task.id
                ),
                0,
            )
            started = time.time()
            context_hash = canonical_hash(context)
            self.run_repository.update_step(
                Step(
                    run_id,
                    task.id,
                    StepStatus.RUNNING.value,
                    prior_attempt + 1,
                    context_hash,
                    None,
                    (),
                    "",
                    self._provider_id(),
                    self._model_id(),
                    task.prompt_template_id,
                    context_hash,
                    started,
                    0.0,
                    request.prompt_version,
                    request.prompt_hash,
                    task_spec_hash(task),
                    "none",
                    0,
                )
            )
            if self._parallel_executor is None:
                self._parallel_executor = ThreadPoolExecutor(
                    max_workers=4,
                    thread_name_prefix="rflp-llm-task",
                )
            future = self._parallel_executor.submit(
                self.executor.execute,
                task,
                context,
                self.methodology_version,
                token_budget=self._output_budget(),
            )
            prepared[task.id] = _PreparedParallelTask(
                current,
                context,
                request,
                prior_attempt,
                started,
                future,
            )
        return prepared

    def _recover_lifecycle_task(
        self,
        project_id: str,
        run_id: str,
        task,
        current,
        context,
        request,
        prior_attempt: int,
        started: float,
        original_diagnostic: str,
    ) -> tuple[bool, tuple[str, ...]] | None:
        """Keep a lifecycle run moving after an LLM task crosses no semantic boundary.

        The fallback is intentionally limited to the typed lifecycle task
        catalog. It does not overwrite the failed LLM proposal; the original
        failure remains in the step diagnostics and the rule patch is marked
        as offline provenance. This makes the graph useful for downstream
        stages while keeping the review trail honest.
        """

        if task.id not in LIFECYCLE_TASKS or self._mode() != "configured":
            return None
        try:
            response = self._lifecycle_fallback_executor.execute(
                task,
                context,
                self.methodology_version,
                evidence_bundle=context.evidence,
                token_budget=self._output_budget(),
            )
            if response.status is not StepStatus.COMPLETED:
                return None
            if response.patch is not None:
                response = replace(
                    response,
                    patch=enrich_architecture_patch(current, response.patch),
                    provider_id="offline",
                    model_id="lifecycle-rule-runtime",
                    input_hash=canonical_hash(context),
                    output_hash=canonical_hash(response.patch),
                )
                self.executor.validate_response(project_id, task, current, context, response)
            patch_id = response.patch.id if response.patch is not None else None
            if response.patch is not None:
                revision = self.model_repository.append_patch(
                    project_id,
                    response.patch,
                    current.revision,
                    run_id=run_id,
                )
                patch_trace = getattr(self.model_repository, "update_patch_trace", None)
                if patch_trace is not None:
                    patch_trace(
                        patch_id,
                        provider_id="offline",
                        model_id="lifecycle-rule-runtime",
                    )
                self._record_audit(
                    project_id,
                    "task.patch",
                    {
                        "run_id": run_id,
                        "task_id": task.id,
                        "patch_id": patch_id,
                        "revision": revision.sequence,
                        "provider_id": "offline",
                        "model_id": "lifecycle-rule-runtime",
                        "recovery": True,
                    },
                )
            else:
                revision = current
            graph = self.model_repository.load_graph(project_id)
            completion = evaluate_completion(task, graph, response)
            diagnostics = tuple(dict.fromkeys(
                (
                    original_diagnostic,
                    "lifecycle:recovered_by_rule_runtime",
                    *response.diagnostics,
                    *completion.issue_codes,
                )
            ))
            status = StepStatus.COMPLETED if completion.passed else StepStatus.DEGRADED
            self.run_repository.update_step(
                Step(
                    run_id,
                    task.id,
                    status.value,
                    prior_attempt + 1,
                    response.input_hash or canonical_hash(context),
                    patch_id,
                    diagnostics,
                    response.output_hash,
                    "offline",
                    "lifecycle-rule-runtime",
                    task.prompt_template_id,
                    canonical_hash(context),
                    started,
                    time.time(),
                    request.prompt_version,
                    request.prompt_hash,
                    task_spec_hash(task),
                    "rule_runtime_fallback",
                    0,
                )
            )
            return completion.passed, diagnostics
        except Exception as exc:
            self._record_audit(
                project_id,
                "task.recovery_failed",
                {
                    "run_id": run_id,
                    "task_id": task.id,
                    "original_diagnostic": original_diagnostic,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            return None

    def _promote_completed_output(
        self,
        project_id: str,
        run_id: str,
        patch: Patch,
        expected_revision: int,
    ):
        """Mark semantically completed LLM output as ready for downstream trace."""

        output_ids = {
            operation.entity.id
            for operation in patch.operations
            if isinstance(operation, AddEntity)
        }
        if not output_ids:
            return self.model_repository.load_graph(project_id).revision
        graph = self.model_repository.load_graph(project_id)
        operations = tuple(
            UpdateEntity(entity_id, {"status": EntityStatus.VALIDATED.value})
            for entity_id in sorted(output_ids)
            if entity_id in graph.entity_index
            and graph.entity_index[entity_id].meta.producer is Producer.LLM
            and graph.entity_index[entity_id].meta.status is EntityStatus.CANDIDATE
        )
        if not operations:
            return graph.revision
        promotion = Patch.create(
            project_id,
            f"{run_id}:promote",
            operations,
            "任务语义检查通过，提升 LLM 输出为 validated",
            expected_revision,
        )
        return self.model_repository.append_patch(
            project_id,
            promotion,
            expected_revision,
            run_id=run_id,
        ).sequence

    def _fail_closed_task(
        self, project_id, phase, identity, task, request, context_hash,
        prior_attempt, started, completed, diagnostics, failure_stage, code, exc,
    ) -> _TaskRunResult:
        message = f"{task.id}: {code}: {type(exc).__name__}: {exc}"
        diagnostic = f"{failure_stage.value}:{code}: {message}"
        diagnostics.append(diagnostic)
        self.run_repository.update_step(Step(
            identity.run_id, task.id, StepStatus.FAILED.value,
            prior_attempt + 1, context_hash, None, (diagnostic,),
            canonical_hash(diagnostic), self._provider_id(), self._model_id(),
            task.prompt_template_id, context_hash, started, time.time(),
            request.prompt_version, request.prompt_hash, task_spec_hash(task),
            "none", 0,
        ))
        self._block_pending_steps(
            project_id,
            identity.run_id,
            f"blocked by {task.id} {failure_stage.value} failure",
            after_task_id=task.id,
        )
        self._update_run_status(identity.run_id, RunStatus.DEGRADED, tuple(diagnostics))
        return _TaskRunResult(False, (diagnostic,), failure_stage)

    def _ensure_run(self, project_id: str, *, run_id: str | None = None, force_new: bool = False, phase: Phase | None = None, tasks=None) -> RunIdentity:
        graph = self.model_repository.load_graph(project_id)
        selected_tasks = tuple(tasks or (task for item in self.orchestrator.phases for task in tasks_for_phase(item)))
        profile = str(getattr(self.runtime_selection, "profile_id", "offline-rule"))
        task_spec_hash_value = canonical_hash(tuple(task_spec_hash(item) for item in selected_tasks))
        prompt_hash = canonical_hash(tuple(
            (item.prompt_template_id, self.executor.prompts.resolve(item.prompt_template_id).version,
             self.executor.prompts.resolve(item.prompt_template_id).prompt_hash)
            for item in selected_tasks
        ))
        identity = RunIdentity.create(project_id, model_profile=profile, methodology_version=self.methodology_version, task_spec_hash=task_spec_hash_value, prompt_hash=prompt_hash, context_hash=graph.snapshot_hash, input_hash=graph.snapshot_hash, force_new=force_new)
        if run_id and not force_new:
            identity = RunIdentity(identity.project_id, identity.model_profile, identity.methodology_version, identity.task_spec_hash, identity.prompt_hash, identity.context_hash, identity.input_hash, run_id)
        existing = self.run_repository.load_run(project_id, identity.run_id)
        if existing is None:
            self.run_repository.create_run(Run(identity.run_id, project_id, "lifecycle" if phase is None else phase.value, RunStatus.RUNNING.value, 0, self.methodology_version, profile, identity.input_hash, (), tuple(Step(identity.run_id, task.id) for task in selected_tasks), self._provider_id(), self._model_id(), self._mode(), identity.context_hash, identity.task_spec_hash, identity.prompt_hash, "", time.time(), 0.0))
            self._record_audit(project_id, "run.created", {"run_id": identity.run_id, "model_profile": profile, "provider_id": self._provider_id(), "model_id": self._model_id(), "task_spec_hash": task_spec_hash_value, "prompt_hash": prompt_hash, "context_hash": identity.context_hash, "input_hash": identity.input_hash})
        if identity.run_id not in self._leases:
            lease = f"lease-{uuid4().hex}"
            claimer = getattr(self.run_repository, "claim_run", None)
            if claimer is None or claimer(project_id, identity.run_id, lease, time.time()):
                self._leases[identity.run_id] = lease
        return identity

    def _block_pending_steps(
        self,
        project_id: str,
        run_id: str,
        reason: str,
        *,
        after_task_id: str | None = None,
    ) -> None:
        stored = self.run_repository.load_run(project_id, run_id)
        if stored is None:
            return
        task_order = [
            task.id
            for phase in self.orchestrator.phases
            for task in tasks_for_phase(phase)
        ]
        start = task_order.index(after_task_id) + 1 if after_task_id in task_order else 0
        pending_ids = set(task_order[start:])
        now = time.time()
        for step in stored.steps:
            if step.task_id not in pending_ids or step.status in {
                StepStatus.COMPLETED.value,
                StepStatus.FAILED.value,
                StepStatus.BLOCKED.value,
            }:
                continue
            self.run_repository.update_step(
                replace(
                    step,
                    status=StepStatus.BLOCKED.value,
                    diagnostics=(reason,),
                    completed_at=now,
                )
            )

    def resume(self, project_id: str, run_id: str) -> RunSummary:
        stored = self.run_repository.load_run(project_id, run_id)
        if stored is None:
            raise ContractViolation(f"run not found: {run_id}")
        if stored.phase == "lifecycle":
            return self.orchestrator.run(project_id, run_id=run_id)
        return self._run_phase(project_id, Phase(stored.phase), run_id=run_id)

    def repair(self, project_id: str, issue_id: str, *, run_id: str | None = None, repair_round: int = 1) -> RunSummary:
        issues = self.model_repository.list_issues(project_id)
        issue = next((item for item in issues if item.get("id") == issue_id), None)
        if issue is None:
            raise ContractViolation(f"repair requires a registered issue: {issue_id}")
        graph = self.model_repository.load_graph(project_id)
        code = str(issue.get("code", "issue"))
        effective_run_id = run_id or f"repair-{issue_id}"
        context = build_repair_context(
            project_id, effective_run_id, issue_id, {**issue, "failing_gate": issue.get("suggested_rollback", "")},
            graph, evidence=tuple(self.model_repository.list_evidence(project_id)),
        )
        repair_task = plan_repair_task(context)
        proposal = LLMRepairStrategy(self.executor).propose(context, repair_task)
        if proposal is None or proposal.patch is None:
            proposal = RuleFallbackRepairStrategy().propose(graph, context, repair_task)
        patch = proposal.patch
        if patch is None:
            return RunSummary(effective_run_id, project_id, Phase.OPERATIONAL, RunStatus.DEGRADED, (), ("repair produced no patch",))
        operations = tuple(
            operation for operation in patch.operations
            if not hasattr(operation, "entity") or operation.entity.id not in graph.entity_index
        )
        if not operations:
            return RunSummary(effective_run_id, project_id, _phase_for_repair_task(repair_task.target_task_id), RunStatus.COMPLETED, (), ("repair already represented in current graph", f"strategy={proposal.strategy}"))
        if operations != patch.operations:
            patch = Patch.create(project_id, patch.task_id, operations, patch.reason, graph.revision)
        repair_response = TaskExecutionResponse(StepStatus.COMPLETED, patch=patch)
        repair_spec = repair_task.as_task_spec(context)
        self.executor.validate_response(project_id, repair_spec, graph, ContextBundle(project_id, repair_spec.id, graph.revision, context.local_entities, context.local_relations, context.evidence), repair_response)
        self.model_repository.append_patch(project_id, patch, graph.revision, run_id=run_id)
        if run_id and self.run_repository.load_run(project_id, run_id) is not None:
            prompt = self.executor.prompts.resolve(repair_spec.prompt_template_id)
            self.run_repository.update_step(Step(
                effective_run_id,
                repair_task.id,
                StepStatus.COMPLETED.value,
                repair_round,
                graph.snapshot_hash,
                patch.id,
                proposal.diagnostics,
                canonical_hash(patch.operations),
                self._provider_id() if proposal.strategy == "llm" else "offline",
                self._model_id() if proposal.strategy == "llm" else "rule-runtime",
                repair_spec.prompt_template_id,
                canonical_hash(context),
                time.time(),
                time.time(),
                prompt.version,
                prompt.prompt_hash,
                task_spec_hash(repair_spec),
                proposal.strategy,
                repair_round,
            ))
        self._record_audit(project_id, "repair.applied", {
            "run_id": run_id, "issue_id": issue_id, "issue_code": code,
            "strategy": proposal.strategy, "repair_round": repair_round, "target_task": proposal.target_task,
            "patch_id": patch.id, "before_hash": graph.snapshot_hash,
            "after_hash": self.model_repository.load_graph(project_id).snapshot_hash,
            "diagnostics": list(proposal.diagnostics),
        })
        return RunSummary(effective_run_id, project_id, _phase_for_repair_task(repair_task.target_task_id), RunStatus.COMPLETED, (), (f"applied_patch={patch.id}", f"strategy={proposal.strategy}", *proposal.diagnostics))

    def gate(self, project_id: str, phase: Phase, *, run_id: str | None = None) -> GateResult:
        graph = self.model_repository.load_graph(project_id)
        result = gate_for_phase(phase, graph)
        saver = getattr(self.model_repository, "save_issue", None)
        if saver is not None:
            for gap in result.issues:
                saver(project_id, {"id": self._issue_id(project_id, result, gap), "code": gap.code, "severity": "error", "entity_ids": list(gap.entity_ids), "suggested_rollback": result.rollback_phase.value if result.rollback_phase else None, "run_id": run_id})
        self._record_audit(project_id, "gate.evaluated", {"run_id": run_id, "gate_id": result.gate_id, "phase": phase.value, "passed": result.passed, "issues": [gap.code for gap in result.issues]})
        return result

    def _issue_id(self, project_id: str, result: GateResult, gap: CoverageGap) -> str:
        graph = self.model_repository.load_graph(project_id)
        return f"issue-{canonical_hash((project_id, result.gate_id, gap.code, graph.revision, gap.entity_ids))[:16]}"

    def _target_task_for_issue(self, code: str) -> str:
        for task in task_catalog():
            for route in task.failure_routes:
                if route.issue_code == code and route.target_task_id:
                    return route.target_task_id
        return {"missing_stakeholder": "stakeholder_analysis", "missing_lifecycle": "lifecycle_analysis", "missing_scenario": "scenario_exploration", "missing_use_case": "use_case_analysis", "missing_requirement": "stakeholder_requirements", "missing_function": "function_identification", "broken_requirement_function_trace": "function_identification", "incomplete_rflp_chain": "logical_analysis", "broken_requirement_rflp_trace": "logical_analysis", "missing_verification": "verification_validation", "broken_requirement_verification_trace": "verification_validation", "missing_validation": "verification_validation", "broken_requirement_validation_trace": "verification_validation"}.get(code, "")

    def _gate_payload(self, result: GateResult, phase: Phase) -> dict[str, object]:
        return {"gate_id": result.gate_id, "phase": phase.value, "passed": result.passed, "issues": [asdict(gap) for gap in result.issues], "checks": list(result.checks)}

    def _update_run_status(self, run_id: str, status: RunStatus, diagnostics: tuple[str, ...]) -> None:
        updater = getattr(self.run_repository, "update_run", None)
        if updater is not None:
            updater(run_id, status.value, diagnostics)

    def _record_audit(self, project_id: str, kind: str, payload: dict[str, object]) -> None:
        recorder = getattr(self.model_repository, "record_audit", None)
        if recorder is not None:
            recorder(project_id, kind, payload)

    def _provider_id(self) -> str:
        return str(getattr(self.runtime_selection, "provider_id", "offline"))

    def _context_budget(self) -> int:
        value = getattr(self.runtime_selection, "context_window", None)
        try:
            # Match RuntimeFactory's default profile window when the offline
            # rule runtime is injected without an explicit selection.
            return max(512, int(value)) if value is not None else 8192
        except (TypeError, ValueError):
            return 8192

    def _configured_output_budget(self) -> bool:
        return getattr(self.runtime_selection, "max_output_tokens", None) is not None

    def _output_budget(self) -> int:
        value = getattr(self.runtime_selection, "max_output_tokens", None)
        try:
            return max(1, int(value)) if value is not None else 2000
        except (TypeError, ValueError):
            return 2000

    def _model_id(self) -> str:
        return str(getattr(self.runtime_selection, "model_id", "rule-runtime"))

    def _mode(self) -> str:
        return str(getattr(self.runtime_selection, "mode", "offline"))


class NoopRuntime:
    """Deterministic no-op runtime retained for focused unit tests."""

    def execute(self, request):
        del request
        return TaskExecutionResponse(StepStatus.COMPLETED)


def _execution_schedule(phase: Phase, tasks, *, parallel_enabled: bool) -> tuple:
    """Return catalog tasks in dependency groups, preserving catalog members."""

    if not parallel_enabled:
        return tuple(tasks)
    by_id = {task.id: task for task in tasks}
    scheduled = []
    for group in _PARALLEL_PHASE_GROUPS.get(phase, ()):
        scheduled.extend(by_id[task_id] for task_id in group if task_id in by_id)
    scheduled_ids = {task.id for task in scheduled}
    scheduled.extend(task for task in tasks if task.id not in scheduled_ids)
    return tuple(scheduled)


def _parallel_groups_by_first_task(phase: Phase, tasks) -> dict[str, tuple]:
    by_id = {task.id: task for task in tasks}
    task_ids = {task.id for task in tasks}
    return {
        group[0]: tuple(by_id[task_id] for task_id in group if task_id in task_ids)
        for group in _PARALLEL_PHASE_GROUPS.get(phase, ())
        if len(group) > 1 and group[0] in task_ids
    }


def _rebase_parallel_patch(project_id: str, task_id: str, patch: Patch, graph) -> Patch | None:
    """Rebase a snapshot patch while keeping independent batch outputs mergeable."""

    entity_ids = set(graph.entity_index)
    relation_keys = {
        (item.source_id, item.predicate, item.target_id)
        for item in graph.relations
    }
    operations = []
    for operation in patch.operations:
        if isinstance(operation, AddEntity):
            if operation.entity.id in entity_ids:
                continue
            entity_ids.add(operation.entity.id)
            operations.append(operation)
        elif isinstance(operation, Relate):
            key = (operation.source_id, operation.predicate, operation.target_id)
            if key in relation_keys:
                continue
            relation_keys.add(key)
            operations.append(operation)
        elif isinstance(operation, (UpdateEntity, Deprecate)):
            entity_id = operation.entity_id
            if entity_id in entity_ids:
                operations.append(operation)
    if not operations:
        return None
    return Patch.create(
        project_id,
        task_id,
        tuple(operations),
        patch.reason,
        graph.revision,
    )


def _phase_for_repair_task(task_id: str) -> Phase:
    if task_id == "function_identification":
        return Phase.FUNCTIONAL
    if task_id in {"logical_analysis", "physical_candidates"}:
        return Phase.LOGICAL_PHYSICAL
    if task_id == "verification_validation":
        return Phase.ASSURANCE
    return Phase.OPERATIONAL
