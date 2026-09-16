"""Product-level natural-language to complete RFLP model generation."""

from __future__ import annotations

from dataclasses import dataclass, replace
import time
from collections.abc import Mapping, Sequence
from uuid import uuid4

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.errors import ConflictError, ContractViolation, InputRequired, MethodologyValidationError
from rflp_lite.domain.model import AddEntity, Patch, UpdateEntity
from rflp_lite.methodology.contracts import (
    ContextBundle,
    RunStatus,
    StepStatus,
    TaskExecutionResponse,
)
from rflp_lite.methodology.completion import evaluate_vertical_stage
from rflp_lite.methodology.context import ContextBuilder
from rflp_lite.methodology.executor import TaskExecutor
from rflp_lite.methodology.engine import MethodologyEngine, MethodologyReport
from rflp_lite.methodology.controller import ControllerPlan, ControllerProposal, SystemsEngineeringController
from rflp_lite.methodology.llm_controller import LLMController
from rflp_lite.methodology.impact import ImpactPlan, TypedImpactPlanner
from rflp_lite.methodology.architecture_persistence import enrich_architecture_patch
from rflp_lite.methodology.tasks import task_spec_hash
from rflp_lite.methodology.vertical_coverage import resolve_requirement_trace
from rflp_lite.methodology.vertical_generation import (
    VerticalStage,
    downstream_vertical_stages,
    stage_required_kinds,
    stage_spec,
    stage_task,
    vertical_stage_specs,
)
from rflp_lite.application.tool_layer import EngineeringToolLayer
from rflp_lite.application.requirement_input import RequirementInputService
from rflp_lite.repository.port import ModelRepository, Run, Step
from rflp_lite.runtime.rule_based import VerticalRuleRuntime


@dataclass(frozen=True, slots=True)
class GenerateModelRequest:
    project_id: str
    requirement_text: str | None = None
    document_ids: tuple[str, ...] = ()
    run_id: str | None = None
    force_new: bool = False


@dataclass(frozen=True, slots=True)
class StageResult:
    stage: str
    status: str
    revision: int
    entity_count: int
    relation_count: int
    assumptions: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    decision_records: tuple[Mapping[str, object], ...] = ()
    completion_checks: tuple[Mapping[str, object], ...] = ()
    completion_issue_codes: tuple[str, ...] = ()
    attempts: int = 1


@dataclass(frozen=True, slots=True)
class TraceabilitySummary:
    rflp_complete_count: int
    rflp_partial_count: int
    rflp_missing_count: int
    verification_complete_count: int
    validation_complete_count: int
    end_to_end_complete_count: int
    end_to_end_partial_count: int
    end_to_end_missing_count: int
    paths: tuple[tuple[str, ...], ...] = ()

    @property
    def complete_count(self) -> int:
        return self.end_to_end_complete_count

    @property
    def partial_count(self) -> int:
        return self.end_to_end_partial_count

    @property
    def missing_count(self) -> int:
        return self.end_to_end_missing_count

    def as_dict(self) -> Mapping[str, object]:
        return {
            "complete_count": self.end_to_end_complete_count,
            "partial_count": self.end_to_end_partial_count,
            "missing_count": self.end_to_end_missing_count,
            "rflp_complete_count": self.rflp_complete_count,
            "rflp_partial_count": self.rflp_partial_count,
            "rflp_missing_count": self.rflp_missing_count,
            "verification_complete_count": self.verification_complete_count,
            "validation_complete_count": self.validation_complete_count,
            "end_to_end_complete_count": self.end_to_end_complete_count,
            "end_to_end_partial_count": self.end_to_end_partial_count,
            "end_to_end_missing_count": self.end_to_end_missing_count,
            "paths": [list(path) for path in self.paths],
        }


@dataclass(frozen=True, slots=True)
class GenerateModelResult:
    run_id: str
    project_id: str
    status: str
    revision: int
    stage_results: tuple[StageResult, ...]
    traceability: TraceabilitySummary
    warnings: tuple[str, ...] = ()
    sysml_text: str = ""
    methodology: MethodologyReport | None = None
    controller: ControllerPlan | None = None

    def as_dict(self) -> Mapping[str, object]:
        return {
            "run_id": self.run_id,
            "project_id": self.project_id,
            "status": self.status,
            "revision": self.revision,
            "stage_results": [
                {
                    "stage": item.stage,
                    "status": item.status,
                    "revision": item.revision,
                    "entity_count": item.entity_count,
                    "relation_count": item.relation_count,
                    "assumptions": list(item.assumptions),
                    "open_questions": list(item.open_questions),
                    "diagnostics": list(item.diagnostics),
                    "decision_records": [dict(record) for record in item.decision_records],
                    "completion_checks": [dict(check) for check in item.completion_checks],
                    "completion_issue_codes": list(item.completion_issue_codes),
                    "attempts": item.attempts,
                }
                for item in self.stage_results
            ],
            "traceability": self.traceability.as_dict(),
            "warnings": list(self.warnings),
            "sysml_text": self.sysml_text,
            "methodology": self.methodology.as_dict() if self.methodology else {},
            "controller": self.controller.as_dict() if self.controller else {},
        }


@dataclass(frozen=True, slots=True)
class _StageExecution:
    result: StageResult | None
    warnings: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _StageAttemptResult:
    result: StageResult | None
    warnings: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    response: TaskExecutionResponse | None = None
    context_hash: str = ""
    started_at: float = 0.0


class ModelGenerationService:
    """Run the product's five-stage model generation path."""

    def __init__(
        self,
        repository: ModelRepository,
        runtime,
        *,
        runtime_selection=None,
        methodology_engine: MethodologyEngine | None = None,
        controller: SystemsEngineeringController | None = None,
        llm_controller: LLMController | None = None,
        tool_layer: EngineeringToolLayer | None = None,
        context_builder: ContextBuilder | None = None,
        methodology_version: str = "v2.1",
        output_budget: int | None = None,
    ) -> None:
        self.repository = repository
        self.runtime = runtime
        self.runtime_selection = runtime_selection
        self.methodology_engine = methodology_engine or MethodologyEngine()
        self.controller = controller or SystemsEngineeringController(self.methodology_engine)
        self.llm_controller = llm_controller
        self.impact_planner = TypedImpactPlanner()
        self.tool_layer = tool_layer or EngineeringToolLayer(repository)
        self.context_builder = context_builder or ContextBuilder()
        self.methodology_version = methodology_version
        self.output_budget = max(
            256,
            int(output_budget or getattr(runtime_selection, "max_output_tokens", None) or 3000),
        )
        self.executor = TaskExecutor(runtime)

    def generate(
        self,
        project_id: str,
        *,
        requirement_text: str | None = None,
        document_ids: tuple[str, ...] = (),
        run_id: str | None = None,
        force_new: bool = False,
    ) -> GenerateModelResult:
        effective_run_id = self.prepare_generation(
            project_id,
            requirement_text=requirement_text,
            document_ids=document_ids,
            run_id=run_id,
            force_new=force_new,
        )
        graph = self.repository.load_graph(project_id)
        stage_results: list[StageResult] = []
        warnings: list[str] = []

        for stage in vertical_stage_specs():
            graph = self.repository.load_graph(project_id)
            execution = self._execute_stage(
                project_id, effective_run_id, stage, graph, document_ids
            )
            if execution.result is None:
                return self._finish_failed(
                    project_id,
                    effective_run_id,
                    stage_results,
                    stage.stage,
                    execution.diagnostics,
                )
            stage_results.append(execution.result)
            warnings.extend(execution.warnings)

        final_graph = self.repository.load_graph(project_id)
        traceability = build_traceability_summary(final_graph)
        methodology = self.methodology_engine.analyze(final_graph)
        controller_plan = self._controller_plan(final_graph, methodology)
        warnings.extend(
            f"{finding.stage}: {finding.code}: {finding.message}"
            for finding in methodology.findings
            if finding.severity == "error"
        )
        if traceability.complete_count:
            status = (
                "completed"
                if not warnings and not traceability.partial_count and not traceability.missing_count
                else "completed_with_warnings"
            )
        else:
            status = "completed_with_warnings"
            warnings.append("没有形成完整的 R→F→L→P→V&V 追溯链")
        self.repository.update_run(effective_run_id, RunStatus.COMPLETED.value, tuple(warnings))
        self._audit(project_id, "model_generation.completed", {
            "run_id": effective_run_id,
            "status": status,
            "revision": final_graph.revision,
            "traceability": traceability.as_dict(),
        })
        self._audit(project_id, "model_generation.methodology_analyzed", {
            "run_id": effective_run_id,
            **methodology.as_dict(),
        })
        self._audit(project_id, "model_generation.controller_planned", {
            "run_id": effective_run_id,
            **controller_plan.as_dict(),
        })
        return GenerateModelResult(
            effective_run_id,
            project_id,
            status,
            final_graph.revision,
            tuple(stage_results),
            traceability,
            tuple(dict.fromkeys(warnings)),
            _sysml_text(final_graph),
            methodology,
            controller_plan,
        )

    def prepare_generation(
        self,
        project_id: str,
        *,
        requirement_text: str | None = None,
        document_ids: tuple[str, ...] = (),
        run_id: str | None = None,
        force_new: bool = False,
    ) -> str:
        """Validate inputs and persist the Run before executing any stage."""

        request = GenerateModelRequest(
            project_id,
            requirement_text,
            tuple(document_ids),
            run_id,
            force_new,
        )
        self._ensure_input(request)
        graph = self.repository.load_graph(project_id)
        effective_run_id = run_id or f"generation-{uuid4().hex[:16]}"
        self._ensure_run(effective_run_id, project_id, graph)
        return effective_run_id

    def impact_plan(
        self,
        project_id: str,
        changed_entity_ids: Sequence[str],
    ) -> ImpactPlan:
        """Return the revision-bound typed impact of one or more graph changes."""

        return self.impact_planner.plan(
            self.repository.load_graph(project_id),
            tuple(changed_entity_ids),
        )

    def reanalyze(
        self,
        project_id: str,
        entity_id: str,
        *,
        run_id: str | None = None,
        expected_revision: int | None = None,
        controller_decision: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        graph = self.repository.load_graph(project_id)
        if expected_revision is not None and int(expected_revision) != graph.revision:
            raise ConflictError(
                f"stale re-analysis request: expected {expected_revision}, current {graph.revision}"
            )
        entity = graph.entity_index.get(entity_id)
        if entity is None:
            raise ContractViolation(f"entity not found: {entity_id}")
        impact = self.impact_planner.plan(graph, (entity_id,))
        stages = tuple(stage_spec(item) for item in impact.selected_stages)
        before_traceability = {
            "revision": graph.revision,
            **build_traceability_summary(graph).as_dict(),
        }
        effective_run_id = run_id or f"reanalysis-{uuid4().hex[:16]}"
        self._ensure_run(
            effective_run_id,
            project_id,
            graph,
            stages=stages,
            phase="vertical_reanalysis",
        )
        stage_results: list[StageResult] = []
        warnings: list[str] = []
        for stage in stages:
            current = self.repository.load_graph(project_id)
            execution = self._execute_stage(
                project_id,
                effective_run_id,
                stage,
                current,
                (),
                controller_decision=controller_decision,
            )
            if execution.result is None:
                failed = self._finish_failed(
                    project_id,
                    effective_run_id,
                    stage_results,
                    stage.stage,
                    execution.diagnostics,
                )
                failed_graph = self.repository.load_graph(project_id)
                return _reanalysis_payload(
                    failed,
                    entity_id,
                    graph.revision,
                    stages,
                    execution_status="failed",
                    controller_decision=controller_decision,
                    impact=impact,
                    before_traceability=before_traceability,
                    after_traceability={
                        "revision": failed_graph.revision,
                        **build_traceability_summary(failed_graph).as_dict(),
                    },
                )
            stage_results.append(execution.result)
            warnings.extend(execution.warnings)
        final_graph = self.repository.load_graph(project_id)
        traceability = build_traceability_summary(final_graph)
        methodology = self.methodology_engine.analyze(
            final_graph,
            changed_entity_ids=(entity_id,),
        )
        controller_plan = self._controller_plan(final_graph, methodology)
        warnings.extend(
            f"{finding.stage}: {finding.code}: {finding.message}"
            for finding in methodology.findings
            if finding.severity == "error"
        )
        if not traceability.complete_count:
            warnings.append("没有形成完整的 R→F→L→P→V&V 追溯链")
        status = "completed" if not warnings else "completed_with_warnings"
        self.repository.update_run(effective_run_id, RunStatus.COMPLETED.value, tuple(warnings))
        self._audit(project_id, "model_generation.completed", {
            "run_id": effective_run_id,
            "status": status,
            "revision": final_graph.revision,
            "traceability": traceability.as_dict(),
        })
        self._audit(project_id, "model_generation.methodology_analyzed", {
            "run_id": effective_run_id,
            **methodology.as_dict(),
        })
        self._audit(project_id, "model_generation.controller_planned", {
            "run_id": effective_run_id,
            "trigger_entity_id": entity_id,
            **controller_plan.as_dict(),
        })
        result = GenerateModelResult(
            effective_run_id,
            project_id,
            status,
            final_graph.revision,
            tuple(stage_results),
            traceability,
            tuple(dict.fromkeys(warnings)),
            _sysml_text(final_graph),
            methodology,
            controller_plan,
        )
        return _reanalysis_payload(
            result,
            entity_id,
            graph.revision,
            stages,
            execution_status="completed",
            controller_decision=controller_decision,
            impact=impact,
            before_traceability=before_traceability,
            after_traceability={
                "revision": final_graph.revision,
                **traceability.as_dict(),
            },
        )

    def continue_generation(
        self,
        project_id: str,
        entity_id: str,
        *,
        expected_revision: int | None = None,
        controller_decision: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        """Continue the product path after a user has reviewed one entity."""

        graph = self.repository.load_graph(project_id)
        if expected_revision is not None and int(expected_revision) != graph.revision:
            raise ConflictError(
                f"stale continuation request: expected {expected_revision}, current {graph.revision}"
            )
        entity = graph.entity_index.get(entity_id)
        if entity is None:
            raise ContractViolation(f"entity not found: {entity_id}")
        if entity.meta.status not in {EntityStatus.ACCEPTED, EntityStatus.LOCKED}:
            raise ContractViolation(
                "only accepted or locked entities can continue generation"
            )
        stages = downstream_vertical_stages(entity.kind)
        if not stages:
            traceability = build_traceability_summary(graph)
            methodology = self.methodology_engine.analyze(
                graph,
                changed_entity_ids=(entity_id,),
            )
            controller_plan = self._controller_plan(graph, methodology)
            return _continuation_noop_payload(
                graph,
                entity_id,
                traceability,
                methodology,
                controller_plan,
            )

        effective_run_id = f"continuation-{uuid4().hex[:16]}"
        self._ensure_run(
            effective_run_id,
            project_id,
            graph,
            stages=stages,
            phase="vertical_continuation",
        )
        self._audit(project_id, "model_generation.continuation.started", {
            "run_id": effective_run_id,
            "trigger_entity_id": entity_id,
            "trigger_revision": graph.revision,
            "selected_stages": [stage.stage.value for stage in stages],
        })
        stage_results: list[StageResult] = []
        warnings: list[str] = []
        for stage in stages:
            current = self.repository.load_graph(project_id)
            execution = self._execute_stage(
                project_id,
                effective_run_id,
                stage,
                current,
                (),
                controller_decision=controller_decision,
            )
            if execution.result is None:
                failed = self._finish_failed(
                    project_id,
                    effective_run_id,
                    stage_results,
                    stage.stage,
                    execution.diagnostics,
                )
                payload = _continuation_payload(
                    failed,
                    entity_id,
                    graph.revision,
                    stages,
                    execution_status="failed",
                    controller_decision=controller_decision,
                )
                self._audit(project_id, "model_generation.continuation.failed", {
                    "run_id": effective_run_id,
                    "trigger_entity_id": entity_id,
                    "stage": stage.stage.value,
                    "diagnostics": list(execution.diagnostics),
                })
                return payload
            stage_results.append(execution.result)
            warnings.extend(execution.warnings)

        final_graph = self.repository.load_graph(project_id)
        traceability = build_traceability_summary(final_graph)
        methodology = self.methodology_engine.analyze(
            final_graph,
            changed_entity_ids=(entity_id,),
        )
        controller_plan = self._controller_plan(final_graph, methodology)
        warnings.extend(
            f"{finding.stage}: {finding.code}: {finding.message}"
            for finding in methodology.findings
            if finding.severity == "error"
        )
        status = "completed" if not warnings else "completed_with_warnings"
        self.repository.update_run(effective_run_id, RunStatus.COMPLETED.value, tuple(warnings))
        result = GenerateModelResult(
            effective_run_id,
            project_id,
            status,
            final_graph.revision,
            tuple(stage_results),
            traceability,
            tuple(dict.fromkeys(warnings)),
            _sysml_text(final_graph),
            methodology,
            controller_plan,
        )
        payload = _continuation_payload(
            result,
            entity_id,
            graph.revision,
            stages,
            execution_status="completed",
            controller_decision=controller_decision,
        )
        self._audit(project_id, "model_generation.continuation.completed", {
            "run_id": effective_run_id,
            "trigger_entity_id": entity_id,
            "revision": final_graph.revision,
            "selected_stages": [stage.stage.value for stage in stages],
            "traceability": traceability.as_dict(),
        })
        return payload

    def controller_plan(
        self,
        project_id: str,
        *,
        changed_entity_ids: tuple[str, ...] = (),
        max_actions: int = 8,
        include_llm: bool = True,
    ) -> Mapping[str, object]:
        """Return the next controller actions without mutating the project.

        Callers that render a latency-sensitive view can request the
        deterministic catalog only and ask for the optional LLM overlay
        separately.  Generation and explicit controller API callers keep the
        historical opt-in-by-default behavior.
        """

        graph = self.repository.load_graph(project_id)
        report = self.methodology_engine.analyze(
            graph,
            changed_entity_ids=changed_entity_ids,
        )
        plan = self._controller_plan(
            graph,
            report,
            include_llm=include_llm,
            max_actions=max_actions,
        )
        if not include_llm and self.llm_controller is not None and self.llm_controller.model is None:
            plan = replace(plan, proposal=ControllerProposal("not_configured", None, None))
        return plan.as_dict()

    def iterate_controller(
        self,
        project_id: str,
        *,
        max_iterations: int = 3,
        expected_revision: int | None = None,
    ) -> Mapping[str, object]:
        """Execute bounded safe Controller actions and re-evaluate after each one."""

        steps_limit = int(max_iterations)
        if not 1 <= steps_limit <= 8:
            raise ContractViolation("max_iterations must be between 1 and 8")
        initial_graph = self.repository.load_graph(project_id)
        if expected_revision is not None and int(expected_revision) != initial_graph.revision:
            raise ConflictError(
                f"stale controller iteration: expected {expected_revision}, "
                f"current {initial_graph.revision}"
            )
        iteration_id = f"controller-iteration-{uuid4().hex[:16]}"
        start_revision = initial_graph.revision
        records: list[Mapping[str, object]] = []
        seen: set[tuple[str, int]] = set()
        terminal_status = "max_iterations"
        self._audit(project_id, "controller.iteration.started", {
            "iteration_id": iteration_id,
            "start_revision": start_revision,
            "max_iterations": steps_limit,
        })
        for sequence in range(1, steps_limit + 1):
            before_graph = self.repository.load_graph(project_id)
            before_report = self.methodology_engine.analyze(before_graph)
            before_plan = self.controller.plan(before_graph, before_report)
            action = before_plan.next_action
            if action is None:
                terminal_status = "completed"
                break
            fingerprint = (action.id, before_graph.revision)
            if fingerprint in seen:
                terminal_status = "no_progress"
                break
            seen.add(fingerprint)
            if action.kind == "trade_study":
                terminal_status = "awaiting_decision"
                break
            if action.kind == "collect_input":
                terminal_status = "awaiting_input"
                break
            if action.kind not in {"reanalyze", "collect_evidence"}:
                terminal_status = "failed"
                break
            execution = self.execute_controller_action(
                project_id,
                action_id=action.id,
                expected_revision=before_graph.revision,
            )
            after_graph = self.repository.load_graph(project_id)
            after_report = self.methodology_engine.analyze(after_graph)
            nested = execution.get("reanalysis", {})
            nested_status = (
                str(nested.get("execution_status", "completed"))
                if isinstance(nested, Mapping)
                else "completed"
            )
            record = {
                "sequence": sequence,
                "action": action.as_dict(),
                "execution_status": execution.get("execution_status", "completed"),
                "revision_before": before_graph.revision,
                "revision_after": after_graph.revision,
                "traceability_before": build_traceability_summary(before_graph).as_dict(),
                "traceability_after": build_traceability_summary(after_graph).as_dict(),
                "finding_codes_before": [item.code for item in before_report.findings],
                "finding_codes_after": [item.code for item in after_report.findings],
                "result": execution,
            }
            records.append(record)
            self._audit(project_id, "controller.iteration.step", {
                "iteration_id": iteration_id,
                **{key: value for key, value in record.items() if key != "result"},
            })
            if execution.get("execution_status") == "awaiting_evidence":
                terminal_status = "awaiting_evidence"
                break
            if nested_status == "failed":
                terminal_status = "failed"
                break
            if after_graph.revision <= before_graph.revision:
                terminal_status = "no_progress"
                break
        final_graph = self.repository.load_graph(project_id)
        final_report = self.methodology_engine.analyze(final_graph)
        final_controller = self._controller_plan(final_graph, final_report)
        if terminal_status == "max_iterations" and not final_controller.actions:
            terminal_status = "completed"
        payload = {
            "iteration_id": iteration_id,
            "project_id": project_id,
            "execution_status": terminal_status,
            "start_revision": start_revision,
            "revision": final_graph.revision,
            "iterations": records,
            "traceability": build_traceability_summary(final_graph).as_dict(),
            "methodology": final_report.as_dict(),
            "controller": final_controller.as_dict(),
        }
        self._audit(project_id, f"controller.iteration.{terminal_status}", {
            "iteration_id": iteration_id,
            "start_revision": start_revision,
            "revision": final_graph.revision,
            "iteration_count": len(records),
        })
        return payload

    def _controller_plan(
        self,
        graph,
        report: MethodologyReport,
        *,
        include_llm: bool = True,
        max_actions: int = 8,
    ) -> ControllerPlan:
        """Attach one read-only proposal to a deterministic controller plan."""

        plan = self.controller.plan(graph, report, max_actions=max_actions)
        if self.llm_controller is None or not include_llm:
            return plan
        return replace(
            plan,
            proposal=self.llm_controller.propose(graph, report, plan),
        )

    def execute_controller_action(
        self,
        project_id: str,
        *,
        action_id: str | None = None,
        option_id: str | None = None,
        expected_revision: int | None = None,
    ) -> Mapping[str, object]:
        """Execute the next safe controller action or wait for its decision/input."""

        graph = self.repository.load_graph(project_id)
        if expected_revision is not None and int(expected_revision) != graph.revision:
            raise ConflictError(
                f"stale controller action: expected {expected_revision}, current {graph.revision}"
            )
        report = self.methodology_engine.analyze(graph)
        plan = self.controller.plan(graph, report)
        action = next(
            (item for item in plan.actions if item.id == action_id),
            plan.next_action if action_id is None else None,
        )
        if action is None:
            raise ContractViolation(f"controller action not found: {action_id}")
        action_payload = action.as_dict()
        if action.kind in {"collect_evidence", "collect_input"}:
            if action.kind == "collect_evidence":
                tool_result = self.tool_layer.collect_evidence(
                    project_id,
                    graph,
                    action_payload,
                )
                for evidence in tool_result.evidence:
                    self.repository.save_evidence(project_id, evidence)
                if tool_result.status == "completed":
                    tool_context = {
                        "action_id": action.id,
                        "kind": "evidence_collected",
                        "tool_id": tool_result.tool_id,
                        "evidence_ids": [
                            str(item.get("id")) for item in tool_result.evidence
                        ],
                    }
                    target_id = _controller_target(graph, action.entity_ids, action.task_id)
                    if target_id is None:
                        raise ContractViolation("evidence action has no editable target")
                    self._audit(project_id, "controller.evidence_collected", {
                        **action_payload,
                        "tool": tool_result.as_dict(),
                    })
                    result = self.reanalyze(
                        project_id,
                        target_id,
                        expected_revision=graph.revision,
                        controller_decision=tool_context,
                    )
                    return {
                        "execution_status": "completed",
                        "action": action_payload,
                        "tool": tool_result.as_dict(),
                        "reanalysis": result,
                    }
                action_payload = {
                    **action_payload,
                    "tool": tool_result.as_dict(),
                }
            audit_kind = (
                "controller.evidence_requested"
                if action.kind == "collect_evidence"
                else "controller.input_requested"
            )
            self._audit(project_id, audit_kind, action_payload)
            return {
                "execution_status": "awaiting_evidence" if action.kind == "collect_evidence" else "awaiting_input",
                "action": action_payload,
                "controller": plan.as_dict(),
            }
        if action.kind == "trade_study":
            option = next(
                (item for item in action.options if str(item.get("id")) == str(option_id)),
                None,
            )
            if option is None:
                self._audit(project_id, "controller.trade_study.proposed", action_payload)
                return {
                    "execution_status": "awaiting_decision",
                    "action": action_payload,
                    "controller": plan.as_dict(),
                }
            task_id = str(option.get("task_id", ""))
            target_id = _controller_target(graph, action.entity_ids, task_id)
            if target_id is None:
                raise ContractViolation("trade study decision has no editable target")
            decision = {
                "action_id": action.id,
                "option_id": str(option["id"]),
                "option": str(option.get("option", "")),
                "task_id": task_id,
                "target_entity_id": target_id,
                "revision": graph.revision,
            }
            self._audit(project_id, "controller.trade_study.decided", decision)
            result = self.reanalyze(
                project_id,
                target_id,
                expected_revision=graph.revision,
                controller_decision=decision,
            )
            return {
                "execution_status": "completed",
                "action": action_payload,
                "decision": decision,
                "reanalysis": result,
            }
        target_id = _controller_target(graph, action.entity_ids, action.task_id)
        if target_id is None:
            raise ContractViolation("controller action has no editable target")
        self._audit(project_id, "controller.action.executing", action_payload)
        result = self.reanalyze(
            project_id,
            target_id,
            expected_revision=graph.revision,
        )
        return {
            "execution_status": "completed",
            "action": action_payload,
            "reanalysis": result,
        }

    def _execute_stage(
        self,
        project_id: str,
        run_id: str,
        stage,
        graph,
        document_ids: tuple[str, ...],
        *,
        controller_decision: Mapping[str, object] | None = None,
    ) -> _StageExecution:
        task = stage_task(stage.stage)
        max_attempts = 2 if self._feedback_enabled() else 1
        warnings: list[str] = []
        previous_execution: _StageAttemptResult | None = None
        for attempt in range(1, max_attempts + 1):
            current = graph if attempt == 1 else self.repository.load_graph(project_id)
            try:
                execution = self._execute_stage_attempt(
                    project_id,
                    run_id,
                    stage,
                    task,
                    current,
                    document_ids,
                    controller_decision=controller_decision,
                    attempt=attempt,
                )
            except Exception as exc:
                if attempt > 1 and previous_execution is not None:
                    return self._continue_after_feedback_failure(
                        project_id,
                        run_id,
                        task,
                        stage,
                        previous_execution,
                        (str(exc),),
                    )
                return _StageExecution(None, diagnostics=(str(exc),))
            if execution.result is None:
                if attempt > 1 and previous_execution is not None:
                    return self._continue_after_feedback_failure(
                        project_id,
                        run_id,
                        task,
                        stage,
                        previous_execution,
                        execution.diagnostics,
                    )
                return _StageExecution(None, diagnostics=execution.diagnostics)
            if attempt < max_attempts and execution.result.status == "needs_review":
                previous_execution = execution
                self._audit(project_id, "model_generation.stage_feedback", {
                    "run_id": run_id,
                    "stage": execution.result.stage,
                    "attempt": attempt,
                    "next_attempt": attempt + 1,
                    "revision": execution.result.revision,
                    "completion_issue_codes": list(execution.result.completion_issue_codes),
                })
                continue
            if (
                execution.result.status == "needs_review"
                and attempt == max_attempts
                and self._completion_bridge_enabled()
            ):
                bridged = self._apply_completion_bridge(
                    project_id,
                    run_id,
                    stage,
                    task,
                    execution,
                    document_ids,
                    controller_decision=controller_decision,
                )
                if bridged is not None:
                    warnings.extend(bridged.warnings)
                    self._finalize_stage_attempt(
                        project_id,
                        run_id,
                        task,
                        bridged,
                    )
                    return _StageExecution(
                        bridged.result,
                        tuple(dict.fromkeys(warnings)),
                    )
            warnings.extend(execution.warnings)
            self._finalize_stage_attempt(
                project_id,
                run_id,
                task,
                execution,
            )
            return _StageExecution(
                execution.result,
                tuple(dict.fromkeys(warnings)),
            )
        return _StageExecution(None, diagnostics=("stage feedback loop exhausted",))

    def _apply_completion_bridge(
        self,
        project_id: str,
        run_id: str,
        stage,
        task,
        execution: _StageAttemptResult,
        document_ids: tuple[str, ...],
        *,
        controller_decision: Mapping[str, object] | None = None,
    ) -> _StageAttemptResult | None:
        """Close an explicit vertical gap after the bounded LLM feedback pass.

        The remote model remains responsible for the substantive proposal. The
        existing deterministic vertical runtime is used only as a typed
        completion bridge when the same-stage feedback pass still leaves a
        checked gap. It reuses the current graph, preserves locked/user-edited
        entities, and contributes only the minimum missing model structure and
        trace links.
        """

        graph = self.repository.load_graph(project_id)
        context = self._context(
            graph,
            task.id,
            document_ids,
            controller_decision=controller_decision,
            full_graph=True,
        )
        bridge_request = self.executor.request(
            task,
            context,
            self.methodology_version,
            evidence_bundle=context.evidence,
            token_budget=self.output_budget,
        )
        bridge_response = VerticalRuleRuntime().execute(bridge_request)
        if bridge_response.status is not StepStatus.COMPLETED or bridge_response.patch is None:
            return None
        bridge_patch = _preserve_existing_bridge_content(graph, bridge_response.patch)
        bridge_patch = enrich_architecture_patch(graph, bridge_patch)
        if bridge_patch != bridge_response.patch:
            bridge_response = replace(bridge_response, patch=bridge_patch)
        self.executor.validate_response(
            project_id,
            task,
            graph,
            context,
            bridge_response,
        )
        patch = _promote_generated_entities(bridge_response.patch, validated=True)
        revision = self.repository.append_patch(
            project_id,
            patch,
            graph.revision,
            run_id=run_id,
        ).sequence
        current = self.repository.load_graph(project_id)
        missing_kinds = self._missing_stage_kinds(current, stage.stage)
        completion = evaluate_vertical_stage(stage.stage, current)
        diagnostics = tuple(dict.fromkeys(
            (
                *execution.result.diagnostics,
                "completion_bridge=vertical-rule",
                *bridge_response.diagnostics,
            )
        ))
        result = replace(
            execution.result,
            status="needs_review" if missing_kinds or completion.issue_codes else "completed",
            revision=revision,
            entity_count=sum(
                1
                for entity in current.entities
                if entity.kind in stage.output_kinds
                and entity.meta.status is not EntityStatus.DEPRECATED
            ),
            relation_count=len(current.relations),
            diagnostics=diagnostics,
            completion_checks=completion.checks,
            completion_issue_codes=completion.issue_codes,
        )
        warning = (
            f"{stage.stage.value}: completion bridge applied after LLM feedback; "
            "bridge provenance is recorded as offline vertical-rule"
        )
        self._audit(project_id, "model_generation.completion_bridge", {
            "run_id": run_id,
            "stage": stage.stage.value,
            "source_provider_id": execution.response.provider_id if execution.response else "",
            "source_model_id": execution.response.model_id if execution.response else "",
            "source_issue_codes": list(execution.result.completion_issue_codes),
            "bridge_patch_id": patch.id,
            "revision": revision,
            "completion_issue_codes": list(completion.issue_codes),
        })
        return replace(
            execution,
            result=result,
            warnings=(warning,),
            response=execution.response,
        )

    def _continue_after_feedback_failure(
        self,
        project_id: str,
        run_id: str,
        task,
        stage,
        previous_execution: _StageAttemptResult,
        diagnostics: tuple[str, ...],
    ) -> _StageExecution:
        """Keep an applied partial stage usable when its retry endpoint disappears."""

        result = previous_execution.result
        if result is None:
            return _StageExecution(None, diagnostics=diagnostics)
        self._finalize_stage_attempt(
            project_id,
            run_id,
            task,
            previous_execution,
        )
        retry_warning = (
            f"{stage.stage.value}: feedback retry failed; continuing with the "
            "previously committed partial result"
        )
        self._audit(project_id, "model_generation.stage_feedback_failed", {
            "run_id": run_id,
            "stage": stage.stage.value,
            "attempt": result.attempts + 1,
            "revision": result.revision,
            "diagnostics": list(diagnostics),
            "continued_with_revision": result.revision,
        })
        return _StageExecution(
            result,
            tuple(dict.fromkeys((*previous_execution.warnings, retry_warning, *diagnostics))),
        )

    def _execute_stage_attempt(
        self,
        project_id: str,
        run_id: str,
        stage,
        task,
        graph,
        document_ids: tuple[str, ...],
        *,
        controller_decision: Mapping[str, object] | None,
        attempt: int,
    ) -> _StageAttemptResult:
        context = self._context(
            graph,
            task.id,
            document_ids,
            controller_decision=controller_decision,
        )
        started = time.time()
        context_hash = canonical_hash(context)
        self.repository.update_step(
            Step(
                run_id,
                task.id,
                StepStatus.RUNNING.value,
                attempt,
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
                "v1",
                "",
                task_spec_hash(task),
                "",
                0,
            )
        )
        response = self.executor.execute(
            task,
            context,
            self.methodology_version,
            evidence_bundle=context.evidence,
            token_budget=self.output_budget,
        )
        if response.status is not StepStatus.COMPLETED:
            return _StageAttemptResult(
                None,
                diagnostics=response.diagnostics,
                response=response,
                context_hash=context_hash,
                started_at=started,
        )
        warnings: list[str] = []
        semantic_invalid = ""
        if response.patch is None:
            if attempt == 1 and not self._stage_already_present(graph, stage.stage):
                return _StageAttemptResult(
                    None,
                    diagnostics=("stage produced no model patch",),
                    response=response,
                    context_hash=context_hash,
                    started_at=started,
                )
            revision = graph.revision
        else:
            enriched_patch = enrich_architecture_patch(graph, response.patch)
            if enriched_patch != response.patch:
                response = replace(response, patch=enriched_patch)
            try:
                self.executor.validate_response(project_id, task, graph, context, response)
            except MethodologyValidationError as exc:
                if exc.code != "semantic_invalid":
                    raise
                semantic_invalid = str(exc)
                relaxed = replace(
                    task,
                    validators=tuple(item for item in task.validators if item != "semantic"),
                )
                self.executor.validate_response(project_id, relaxed, graph, context, response)
            patch = _promote_generated_entities(response.patch, validated=not semantic_invalid)
            revision = self.repository.append_patch(
                project_id, patch, graph.revision, run_id=run_id
            ).sequence
            if semantic_invalid:
                self._save_semantic_issue(project_id, run_id, task.id, patch, semantic_invalid)
                warnings.append(f"{stage.stage.value}: semantic_invalid: {semantic_invalid}")
        current = self.repository.load_graph(project_id)
        missing_kinds = self._missing_stage_kinds(current, stage.stage)
        completion = evaluate_vertical_stage(stage.stage, current)
        if missing_kinds:
            warnings.append(
                f"{stage.stage.value}: missing required kinds: "
                + ", ".join(kind.value for kind in missing_kinds)
            )
        completion_warning = _stage_completion_warning(stage.stage.value, completion.issue_codes)
        if completion_warning:
            warnings.append(completion_warning)
        stage_result = StageResult(
            stage.stage.value,
            "needs_review"
            if semantic_invalid or missing_kinds or completion.issue_codes
            else "completed",
            revision,
            sum(
                1
                for entity in current.entities
                if entity.kind in stage.output_kinds
                and entity.meta.status is not EntityStatus.DEPRECATED
            ),
            len(current.relations),
            tuple(response.assumptions),
            tuple(response.open_questions),
            tuple(response.diagnostics),
            tuple(response.decision_records),
            completion.checks,
            completion.issue_codes,
            attempt,
        )
        warnings.extend(response.open_questions)
        return _StageAttemptResult(
            stage_result,
            tuple(warnings),
            response=response,
            context_hash=context_hash,
            started_at=started,
        )

    def _finalize_stage_attempt(
        self,
        project_id: str,
        run_id: str,
        task,
        execution: _StageAttemptResult,
    ) -> None:
        response = execution.response
        result = execution.result
        if response is None or result is None:
            return
        self.repository.update_step(
            Step(
                run_id,
                task.id,
                StepStatus.COMPLETED.value,
                result.attempts,
                response.input_hash or execution.context_hash,
                response.patch.id if response.patch else None,
                tuple(dict.fromkeys((*response.diagnostics, *result.diagnostics))),
                response.output_hash,
                response.provider_id or self._provider_id(),
                response.model_id or self._model_id(),
                task.prompt_template_id,
                execution.context_hash,
                execution.started_at,
                time.time(),
                "v1",
                "",
                task_spec_hash(task),
                "",
                0,
            )
        )
        self._audit(project_id, "model_generation.stage_completed", {
            "run_id": run_id,
            "stage": result.stage,
            "status": result.status,
            "revision": result.revision,
            "entity_count": result.entity_count,
            "relation_count": result.relation_count,
            "assumptions": list(result.assumptions),
            "open_questions": list(result.open_questions),
            "diagnostics": list(result.diagnostics),
            "decision_records": [dict(record) for record in result.decision_records],
            "completion_checks": [dict(check) for check in result.completion_checks],
            "completion_issue_codes": list(result.completion_issue_codes),
            "attempts": result.attempts,
        })

    def _ensure_input(self, request: GenerateModelRequest) -> None:
        graph = self.repository.load_graph(request.project_id)
        explicit_text = str(request.requirement_text or "").strip()
        if explicit_text or request.document_ids or self.repository.has_documents(request.project_id):
            RequirementInputService(self.repository, request.project_id).ensure(
                text=explicit_text or None,
                document_ids=request.document_ids,
            )
            return
        if graph.has_active_entities:
            return
        raise InputRequired("requirement_text or an existing requirement is required")

    def _context(
        self,
        graph,
        task_id: str,
        document_ids: tuple[str, ...],
        *,
        controller_decision: Mapping[str, object] | None = None,
        full_graph: bool | None = None,
    ) -> ContextBundle:
        task = stage_task(task_id.removeprefix("vertical."))
        context_budget = self._context_budget()
        output_reserve = min(self.output_budget, max(512, context_budget // 2))
        evidence_bundle = tuple(self.repository.list_evidence(graph.project_id))
        if document_ids:
            selected = set(document_ids)
            evidence_bundle = tuple(
                item
                for item in evidence_bundle
                if str(item.get("source_id", item.get("document_id", ""))) in selected
            )
        context = self.context_builder.build(
            graph,
            task,
            token_budget=context_budget,
            output_reserve=output_reserve,
            prompt_reserve=256,
            evidence_bundle=evidence_bundle,
            full_graph=(
                bool(getattr(self.runtime, "requires_complete_context", False))
                if full_graph is None
                else full_graph
            ),
        )
        evidence = context.evidence
        return replace(
            context,
            task_id=task_id,
            controller_decisions=(dict(controller_decision),) if controller_decision else (),
            evidence=evidence,
        )

    def _context_budget(self) -> int:
        value = getattr(self.runtime_selection, "context_window", None)
        try:
            return max(2048, int(value)) if value is not None else 12000
        except (TypeError, ValueError):
            return 12000
    def _ensure_run(
        self,
        run_id: str,
        project_id: str,
        graph,
        *,
        stages=None,
        phase: str = "vertical_generation",
    ) -> None:
        existing = self.repository.load_run(project_id, run_id)
        if existing is not None:
            return
        selected_stages = tuple(stages or (item for item in vertical_stage_specs()))
        tasks = tuple(stage_task(item.stage) for item in selected_stages)
        task_hash = canonical_hash(tuple(task_spec_hash(item) for item in tasks))
        prompt_hash = canonical_hash(tuple(item.prompt_template_id for item in tasks))
        self.repository.create_run(
            Run(
                run_id,
                project_id,
                phase,
                RunStatus.RUNNING.value,
                0,
                self.methodology_version,
                str(getattr(self.runtime_selection, "profile_id", "offline-rule")),
                graph.snapshot_hash,
                (),
                tuple(Step(run_id, item.id) for item in tasks),
                self._provider_id(),
                self._model_id(),
                self._mode(),
                graph.snapshot_hash,
                task_hash,
                prompt_hash,
                "",
                time.time(),
                0.0,
            )
        )
        self._audit(project_id, "model_generation.started", {
            "run_id": run_id,
            "provider_id": self._provider_id(),
            "model_id": self._model_id(),
        })

    def _stage_already_present(self, graph, stage: VerticalStage) -> bool:
        return not self._missing_stage_kinds(graph, stage)

    def _missing_stage_kinds(self, graph, stage: VerticalStage) -> tuple[EntityKind, ...]:
        required = stage_required_kinds(stage)
        return tuple(
            sorted(
                (
                    kind for kind in required
                    if not any(
                        entity.kind is kind
                        and entity.meta.status is not EntityStatus.DEPRECATED
                        for entity in graph.entities
                    )
                ),
                key=lambda item: item.value,
            )
        )

    def _save_semantic_issue(
        self,
        project_id: str,
        run_id: str,
        task_id: str,
        patch: Patch,
        diagnostic: str,
    ) -> None:
        entity_ids = []
        for operation in patch.operations:
            if isinstance(operation, AddEntity):
                entity_ids.append(operation.entity.id)
            elif isinstance(operation, UpdateEntity):
                entity_ids.append(operation.entity_id)
        self.repository.save_issue(
            project_id,
            {
                "id": f"issue-{canonical_hash((run_id, task_id, diagnostic))[:16]}",
                "run_id": run_id,
                "task_id": task_id,
                "code": "semantic_invalid",
                "severity": "warning",
                "entity_ids": entity_ids,
                "suggested_rollback": task_id,
                "status": "open",
            },
        )

    def _finish_failed(
        self,
        project_id: str,
        run_id: str,
        completed: list[StageResult],
        stage: VerticalStage,
        diagnostics: tuple[str, ...],
    ) -> GenerateModelResult:
        message = tuple(str(item) for item in diagnostics if str(item)) or ("generation failed",)
        self.repository.update_run(run_id, RunStatus.FAILED.value, message)
        self._audit(project_id, "model_generation.failed", {
            "run_id": run_id,
            "stage": stage.value,
            "diagnostics": list(message),
        })
        graph = self.repository.load_graph(project_id)
        return GenerateModelResult(
            run_id,
            project_id,
            "failed",
            graph.revision,
            tuple(completed),
            build_traceability_summary(graph),
            message,
            _sysml_text(graph),
            self.methodology_engine.analyze(graph),
            self.controller.plan(graph),
        )

    def _provider_id(self) -> str:
        return str(getattr(self.runtime_selection, "provider_id", "offline"))

    def _model_id(self) -> str:
        return str(getattr(self.runtime_selection, "model_id", "rule-runtime"))

    def _mode(self) -> str:
        return str(getattr(self.runtime_selection, "mode", "offline"))

    def _feedback_enabled(self) -> bool:
        """Enable one same-stage retry only for structured model runtimes."""

        return (
            self._mode() in {"configured", "injected"}
            and hasattr(self.runtime, "model")
            and bool(
                getattr(
                    self.runtime.model,
                    "automatic_vertical_stage_feedback",
                    True,
                )
            )
        )

    def _completion_bridge_enabled(self) -> bool:
        """Use the deterministic bridge only for a configured model run."""

        return (
            self._mode() == "configured"
            and hasattr(self.runtime, "model")
            and bool(
                getattr(
                    self.runtime.model,
                    "automatic_vertical_stage_feedback",
                    True,
                )
            )
        )

    def _audit(self, project_id: str, kind: str, payload: Mapping[str, object]) -> None:
        recorder = getattr(self.repository, "record_audit", None)
        if recorder is not None:
            recorder(project_id, kind, payload)


def _stage_completion_warning(stage: str, issue_codes: Sequence[str]) -> str:
    if not issue_codes:
        return ""
    return f"{stage}: internal completion issues: " + ", ".join(issue_codes)


def _controller_target(graph, entity_ids: tuple[str, ...], task_id: str) -> str | None:
    """Choose a canonical graph seed for a controller action."""

    entities = tuple(
        graph.entity_index[entity_id]
        for entity_id in entity_ids
        if entity_id in graph.entity_index
    )
    preferred = {
        "requirements": (EntityKind.REQUIREMENT, EntityKind.CONCERN, EntityKind.ACTIVITY),
        "functional": (EntityKind.FUNCTION, EntityKind.REQUIREMENT),
        "logical": (EntityKind.LOGICAL_COMPONENT, EntityKind.STATE, EntityKind.FUNCTION),
        "physical": (EntityKind.PHYSICAL_BLOCK, EntityKind.LOGICAL_COMPONENT),
        "assurance": (
            EntityKind.VERIFICATION_CASE,
            EntityKind.VALIDATION_CASE,
            EntityKind.HAZARD,
            EntityKind.FAILURE_MODE,
            EntityKind.REQUIREMENT,
        ),
    }
    stage = {
        "system_definition": "requirements",
        "stakeholder_analysis": "requirements",
        "stakeholder_requirements": "requirements",
        "lifecycle_analysis": "requirements",
        "scenario_exploration": "requirements",
        "use_case_analysis": "requirements",
        "operational_scenario": "requirements",
        "activity_analysis": "requirements",
        "system_requirement_derivation": "requirements",
        "function_identification": "functional",
        "functional_decomposition": "functional",
        "functional_interaction": "functional",
        "logical_analysis": "logical",
        "dependency_clustering": "logical",
        "architecture_evaluation": "logical",
        "interface_sequence_state": "logical",
        "physical_candidates": "physical",
        "allocation_tradeoff": "physical",
        "technical_requirement": "physical",
        "constraint_propagation": "physical",
        "feasibility_selection": "physical",
        "fmea_stpa_hazard": "assurance",
        "verification_validation": "assurance",
        "reverse_feasibility": "assurance",
        "global_cross_analysis": "assurance",
    }.get(task_id, "assurance")
    for kind in preferred[stage]:
        match = next((entity for entity in entities if entity.kind is kind), None)
        if match is not None:
            return match.id
    return entities[0].id if entities else None


def _reanalysis_payload(
    result: GenerateModelResult,
    entity_id: str,
    trigger_revision: int,
    stages,
    *,
    execution_status: str,
    controller_decision: Mapping[str, object] | None = None,
    impact: ImpactPlan | None = None,
    before_traceability: Mapping[str, object] | None = None,
    after_traceability: Mapping[str, object] | None = None,
):
    payload = dict(result.as_dict())
    payload.update({
        "entity_id": entity_id,
        "trigger_revision": trigger_revision,
        "selected_stages": [stage.stage.value for stage in stages],
        "execution_status": execution_status,
        "execution_status_label": "重新分析已完成" if execution_status == "completed" else "重新分析失败",
    })
    if controller_decision:
        payload["controller_decision"] = dict(controller_decision)
    if impact is not None:
        payload["impact"] = impact.as_dict()
        payload["impacted_vv_case_ids"] = [
            *impact.verification_case_ids,
            *impact.validation_case_ids,
        ]
    if before_traceability is not None:
        payload["before_traceability"] = dict(before_traceability)
    if after_traceability is not None:
        payload["after_traceability"] = dict(after_traceability)
    return payload


def _continuation_payload(
    result: GenerateModelResult,
    entity_id: str,
    trigger_revision: int,
    stages,
    *,
    execution_status: str,
    controller_decision: Mapping[str, object] | None = None,
):
    payload = dict(result.as_dict())
    payload.update({
        "trigger_entity_id": entity_id,
        "entity_id": entity_id,
        "trigger_revision": trigger_revision,
        "selected_stages": [stage.stage.value for stage in stages],
        "execution_status": execution_status,
        "execution_status_label": (
            "下游生成已完成"
            if execution_status == "completed"
            else "下游生成失败"
        ),
    })
    if controller_decision:
        payload["controller_decision"] = dict(controller_decision)
    return payload


def _continuation_noop_payload(
    graph,
    entity_id: str,
    traceability: TraceabilitySummary,
    methodology: MethodologyReport,
    controller: ControllerPlan,
) -> Mapping[str, object]:
    return {
        "run_id": None,
        "project_id": graph.project_id,
        "status": "completed",
        "revision": graph.revision,
        "stage_results": [],
        "traceability": traceability.as_dict(),
        "warnings": [],
        "sysml_text": _sysml_text(graph),
        "methodology": methodology.as_dict(),
        "controller": controller.as_dict(),
        "trigger_entity_id": entity_id,
        "entity_id": entity_id,
        "trigger_revision": graph.revision,
        "selected_stages": [],
        "execution_status": "no_downstream_work",
        "execution_status_label": "没有可继续的下游阶段",
    }


def _promote_generated_entities(patch: Patch, *, validated: bool = True) -> Patch:
    target_status = EntityStatus.VALIDATED if validated else EntityStatus.CANDIDATE
    operations = []
    for operation in patch.operations:
        if isinstance(operation, AddEntity) and operation.entity.meta.producer is Producer.LLM:
            operations.append(
                AddEntity(
                    replace(
                        operation.entity,
                        meta=replace(operation.entity.meta, status=target_status),
                    )
                )
            )
        else:
            operations.append(operation)
    return replace(patch, operations=tuple(operations))


def _preserve_existing_bridge_content(graph, patch: Patch) -> Patch:
    """Merge bridge fields only where an existing LLM entity has a gap."""

    operations = []
    for operation in patch.operations:
        if not isinstance(operation, UpdateEntity):
            operations.append(operation)
            continue
        current = graph.entity_index.get(operation.entity_id)
        if current is None:
            operations.append(operation)
            continue
        field_patch = dict(operation.field_patch)
        # The completion bridge must not rename or replace an LLM-produced
        # engineering object. Its payload is only a source of missing typed
        # fields and nested completion evidence.
        field_patch.pop("name", None)
        candidate_payload = field_patch.get("payload")
        if isinstance(candidate_payload, Mapping):
            field_patch["payload"] = _merge_missing_payload(
                current.payload,
                candidate_payload,
            )
        if field_patch:
            operations.append(UpdateEntity(operation.entity_id, field_patch))
    if tuple(operations) == patch.operations:
        return patch
    return Patch.create(
        patch.project_id,
        patch.task_id,
        tuple(operations),
        patch.reason,
        patch.expected_revision,
    )


def _merge_missing_payload(
    current: Mapping[str, object],
    candidate: Mapping[str, object],
) -> Mapping[str, object]:
    """Recursively add empty/missing fields without overwriting model content."""

    merged = dict(current)
    for key, value in candidate.items():
        if key not in merged or _payload_value_empty(merged[key]):
            merged[key] = value
        elif isinstance(merged[key], Mapping) and isinstance(value, Mapping):
            merged[key] = _merge_missing_payload(merged[key], value)
    return merged


def _payload_value_empty(value: object) -> bool:
    return value is None or value == "" or value == [] or value == {}


def build_traceability_summary(graph) -> TraceabilitySummary:
    active = [
        entity for entity in graph.entities
        if entity.kind is EntityKind.REQUIREMENT
        and entity.meta.status not in {EntityStatus.REJECTED, EntityStatus.DEPRECATED}
    ]
    rflp_complete = 0
    rflp_partial = 0
    rflp_missing = 0
    verification_complete = 0
    validation_complete = 0
    end_to_end_complete = 0
    end_to_end_partial = 0
    end_to_end_missing = 0
    paths: list[tuple[str, ...]] = []
    for requirement in sorted(active, key=lambda item: item.id):
        trace = resolve_requirement_trace(graph, requirement.id)
        functions = trace.function_ids
        logical = trace.logical_component_ids
        physical = trace.physical_ids
        verification = trace.verification_case_ids if trace.stage_coverage["verification"] else ()
        validation = trace.validation_case_ids if trace.stage_coverage["validation"] else ()
        rflp = all(
            trace.stage_coverage[key]
            for key in ("functional", "logical", "physical")
        )
        if rflp:
            rflp_complete += 1
        elif functions or logical or physical:
            rflp_partial += 1
        else:
            rflp_missing += 1
        verification_complete += bool(verification)
        validation_complete += bool(validation)
        end_to_end = trace.complete
        if end_to_end:
            end_to_end_complete += 1
        elif rflp or verification or validation:
            end_to_end_partial += 1
        else:
            end_to_end_missing += 1
        path = tuple(dict.fromkeys((*trace.primary_path, *verification[:1], *validation[:1])))
        paths.append(path)
    return TraceabilitySummary(
        rflp_complete,
        rflp_partial,
        rflp_missing,
        verification_complete,
        validation_complete,
        end_to_end_complete,
        end_to_end_partial,
        end_to_end_missing,
        tuple(paths),
    )


def _sysml_text(graph) -> str:
    try:
        from rflp_lite.application.sysml_v2 import graph_to_sysml
        return graph_to_sysml(graph)
    except (ImportError, AttributeError):
        return ""
