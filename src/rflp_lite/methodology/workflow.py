"""Task execution and the single durable methodology lifecycle."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
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
from rflp_lite.domain.model import Patch
from rflp_lite.methodology.context import ContextBuilder
from rflp_lite.methodology.completion import evaluate_completion
from rflp_lite.methodology.contracts import ContextBundle, FailureStage, Phase, RunStatus, StepStatus, TaskExecutionResponse, TaskRuntime
from rflp_lite.methodology.coverage import CoverageGap, CoverageReport
from rflp_lite.methodology.executor import TaskExecutor
from rflp_lite.methodology.gates import GateResult, gate_for_phase
from rflp_lite.methodology.identity import RunIdentity
from rflp_lite.methodology.repair import patch_for_plan, plan_repair
from rflp_lite.methodology.repair_context import build_repair_context
from rflp_lite.methodology.repair_planner import plan as plan_repair_task
from rflp_lite.methodology.repair_strategies import LLMRepairStrategy, RuleFallbackRepairStrategy
from rflp_lite.methodology.tasks import task_catalog, task_spec_hash, tasks_for_phase
from rflp_lite.repository.port import Run, RunRepository, Step
from rflp_lite.retrieval.evidence import RetrievalEngine


_NON_SEMANTIC_FAILURE_STAGES = frozenset({
    FailureStage.STRUCTURAL,
    FailureStage.COMPILER,
    FailureStage.TRANSPORT,
    FailureStage.CONCURRENCY,
    FailureStage.INTERNAL,
})


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
            if phase_summary.failure_stage in _NON_SEMANTIC_FAILURE_STAGES:
                diagnostics.append(f"{phase.value}: {phase_summary.failure_stage.value} failure; semantic repair skipped")
                self.runner._block_pending_steps(
                    project_id,
                    identity.run_id,
                    f"blocked by {phase.value} {phase_summary.failure_stage.value} failure",
                )
                self.runner._update_run_status(identity.run_id, RunStatus.DEGRADED, tuple(diagnostics))
                completed_phases = {item["phase"] for item in phase_results}
                for pending in self.phases:
                    if pending.value not in completed_phases:
                        phase_results.append({"phase": pending.value, "status": StepStatus.BLOCKED.value, "completed_tasks": [], "diagnostics": [f"Blocked by {phase_summary.failure_stage.value} failure"]})
                phase_results.append({"phase": Phase.CLOSURE.value, "status": "blocked", "completed_tasks": [], "diagnostics": [f"{phase_summary.failure_stage.value} failure must be resolved before Closure"]})
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
        completed_before = {step.task_id for step in (existing.steps if existing else ()) if step.status == StepStatus.COMPLETED.value}
        completed = set(completed_before)
        diagnostics: list[str] = []
        for task in tasks:
            if task.id in completed_before and (rerun_task_ids is None or task.id not in rerun_task_ids):
                continue
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
            prior_attempt = next((step.attempt for step in (existing.steps if existing else ()) if step.task_id == task.id), 0)
            started = time.time()
            context_hash = canonical_hash(context)
            self.run_repository.update_step(Step(identity.run_id, task.id, StepStatus.RUNNING.value, prior_attempt + 1, context_hash, None, (), "", self._provider_id(), self._model_id(), task.prompt_template_id, context_hash, started, 0.0, request.prompt_version, request.prompt_hash, task_spec_hash(task), "none", 0))
            try:
                response = self.executor.execute(
                    task,
                    context,
                    self.methodology_version,
                    token_budget=self._output_budget(),
                )
                patch_id = None
                if response.patch is not None and response.status is not StepStatus.COMPLETED:
                    raise WorkflowInvariantError(
                        "non-completed response cannot carry a committable patch"
                    )
                if response.status is StepStatus.COMPLETED:
                    self.executor.validate_response(project_id, task, current, context, response)
                if response.patch is not None:
                    revision = self.model_repository.append_patch(project_id, response.patch, current.revision, run_id=identity.run_id)
                    patch_id = response.patch.id
                    patch_trace = getattr(self.model_repository, "update_patch_trace", None)
                    if patch_trace is not None:
                        patch_trace(patch_id, provider_id=response.provider_id or self._provider_id(), model_id=response.model_id or self._model_id())
                    self._record_audit(project_id, "task.patch", {"run_id": identity.run_id, "task_id": task.id, "patch_id": patch_id, "revision": revision.sequence, "input_hash": response.input_hash, "output_hash": response.output_hash})
                if response.failure_stage in _NON_SEMANTIC_FAILURE_STAGES:
                    diagnostics.extend(response.diagnostics)
                    self.run_repository.update_step(Step(identity.run_id, task.id, StepStatus.FAILED.value, prior_attempt + 1, response.input_hash or context_hash, patch_id, response.diagnostics, response.output_hash, response.provider_id or self._provider_id(), response.model_id or self._model_id(), task.prompt_template_id, context_hash, started, time.time(), request.prompt_version, request.prompt_hash, task_spec_hash(task), "none", 0))
                    self._block_pending_steps(
                        project_id,
                        identity.run_id,
                        f"blocked by {task.id} {response.failure_stage.value} failure",
                        after_task_id=task.id,
                    )
                    self._update_run_status(identity.run_id, RunStatus.DEGRADED, tuple(diagnostics))
                    return RunSummary(identity.run_id, project_id, phase, RunStatus.DEGRADED, tuple(sorted(completed)), tuple(diagnostics), failure_stage=response.failure_stage)
                completion = evaluate_completion(task, self.model_repository.load_graph(project_id), response)
                if not completion.passed:
                    response = replace(response, status=StepStatus.DEGRADED, diagnostics=tuple(response.diagnostics) + completion.issue_codes)
                if response.status is StepStatus.COMPLETED:
                    completed.add(task.id)
                else:
                    diagnostics.extend(response.diagnostics)
                self.run_repository.update_step(Step(identity.run_id, task.id, response.status.value, prior_attempt + 1, response.input_hash or context_hash, patch_id, response.diagnostics, response.output_hash, response.provider_id or self._provider_id(), response.model_id or self._model_id(), task.prompt_template_id, context_hash, started, time.time(), request.prompt_version, request.prompt_hash, task_spec_hash(task), "none", 0))
            except MethodologyValidationError as exc:
                message = f"{task.id}: semantic validation: {exc}"
                diagnostics.append(message)
                self.run_repository.update_step(Step(
                    identity.run_id, task.id, StepStatus.DEGRADED.value,
                    prior_attempt + 1, context_hash, None, (message,), "",
                    self._provider_id(), self._model_id(), task.prompt_template_id,
                    context_hash, started, time.time(), request.prompt_version,
                    request.prompt_hash, task_spec_hash(task), "none", 0,
                ))
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
        status = RunStatus.COMPLETED if len(completed) == len(tasks) else RunStatus.DEGRADED
        self._update_run_status(identity.run_id, status, tuple(diagnostics))
        return RunSummary(identity.run_id, project_id, phase, status, tuple(sorted(completed)), tuple(diagnostics))

    def _fail_closed_task(
        self, project_id, phase, identity, task, request, context_hash,
        prior_attempt, started, completed, diagnostics, failure_stage, code, exc,
    ) -> RunSummary:
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
        return RunSummary(
            identity.run_id,
            project_id,
            phase,
            RunStatus.DEGRADED,
            tuple(sorted(completed)),
            tuple(diagnostics),
            failure_stage=failure_stage,
        )

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
        return {"missing_stakeholder": "stakeholder_analysis", "missing_lifecycle": "lifecycle_analysis", "missing_scenario": "scenario_exploration", "missing_use_case": "use_case_analysis", "missing_requirement": "stakeholder_requirements", "missing_function": "function_identification", "broken_requirement_function_trace": "function_identification", "incomplete_rflp_chain": "logical_analysis", "broken_requirement_rflp_trace": "logical_analysis", "missing_verification": "verification_validation", "broken_requirement_verification_trace": "verification_validation"}.get(code, "")

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
            return max(512, int(value)) if value is not None else 2000
        except (TypeError, ValueError):
            return 2000

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


def _phase_for_repair_task(task_id: str) -> Phase:
    if task_id == "function_identification":
        return Phase.FUNCTIONAL
    if task_id in {"logical_analysis", "physical_candidates"}:
        return Phase.LOGICAL_PHYSICAL
    if task_id == "verification_validation":
        return Phase.ASSURANCE
    return Phase.OPERATIONAL
