"""Product-level natural-language to complete RFLP model generation."""

from __future__ import annotations

from dataclasses import dataclass, replace
import time
from collections.abc import Mapping
from uuid import uuid4

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.errors import ConflictError, ContractViolation, InputRequired, MethodologyValidationError
from rflp_lite.domain.model import AddEntity, Patch, UpdateEntity
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.contracts import (
    ContextBundle,
    RunStatus,
    StepStatus,
)
from rflp_lite.methodology.executor import TaskExecutor
from rflp_lite.methodology.engine import MethodologyEngine, MethodologyReport
from rflp_lite.methodology.tasks import task_spec_hash
from rflp_lite.methodology.vertical_generation import (
    VerticalStage,
    stage_required_kinds,
    stage_task,
    vertical_stage_specs,
)
from rflp_lite.repository.port import ModelRepository, Run, Step


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
                }
                for item in self.stage_results
            ],
            "traceability": self.traceability.as_dict(),
            "warnings": list(self.warnings),
            "sysml_text": self.sysml_text,
            "methodology": self.methodology.as_dict() if self.methodology else {},
        }


@dataclass(frozen=True, slots=True)
class _StageExecution:
    result: StageResult | None
    warnings: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()


class ModelGenerationService:
    """Run the product's five-stage model generation path."""

    def __init__(
        self,
        repository: ModelRepository,
        runtime,
        *,
        runtime_selection=None,
        methodology_engine: MethodologyEngine | None = None,
        methodology_version: str = "v2.1",
        output_budget: int | None = None,
    ) -> None:
        self.repository = repository
        self.runtime = runtime
        self.runtime_selection = runtime_selection
        self.methodology_engine = methodology_engine or MethodologyEngine()
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
        )

    def reanalyze(
        self,
        project_id: str,
        entity_id: str,
        *,
        run_id: str | None = None,
        expected_revision: int | None = None,
    ) -> Mapping[str, object]:
        graph = self.repository.load_graph(project_id)
        if expected_revision is not None and int(expected_revision) != graph.revision:
            raise ConflictError(
                f"stale re-analysis request: expected {expected_revision}, current {graph.revision}"
            )
        entity = graph.entity_index.get(entity_id)
        if entity is None:
            raise ContractViolation(f"entity not found: {entity_id}")
        stages = _reanalysis_stages(entity.kind)
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
            execution = self._execute_stage(project_id, effective_run_id, stage, current, ())
            if execution.result is None:
                failed = self._finish_failed(
                    project_id,
                    effective_run_id,
                    stage_results,
                    stage.stage,
                    execution.diagnostics,
                )
                return _reanalysis_payload(
                    failed,
                    entity_id,
                    graph.revision,
                    stages,
                    execution_status="failed",
                )
            stage_results.append(execution.result)
            warnings.extend(execution.warnings)
        final_graph = self.repository.load_graph(project_id)
        traceability = build_traceability_summary(final_graph)
        methodology = self.methodology_engine.analyze(
            final_graph,
            changed_entity_ids=(entity_id,),
        )
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
        )
        return _reanalysis_payload(
            result,
            entity_id,
            graph.revision,
            stages,
            execution_status="completed",
        )

    def _execute_stage(
        self,
        project_id: str,
        run_id: str,
        stage,
        graph,
        document_ids: tuple[str, ...],
    ) -> _StageExecution:
        task = stage_task(stage.stage)
        context = self._context(graph, task.id, document_ids)
        started = time.time()
        context_hash = canonical_hash(context)
        self.repository.update_step(
            Step(
                run_id,
                task.id,
                StepStatus.RUNNING.value,
                1,
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
        try:
            response = self.executor.execute(
                task,
                context,
                self.methodology_version,
                evidence_bundle=context.evidence,
                token_budget=self.output_budget,
            )
            if response.status is not StepStatus.COMPLETED:
                return _StageExecution(None, diagnostics=response.diagnostics)
            warnings: list[str] = []
            semantic_invalid = ""
            if response.patch is None:
                if not self._stage_already_present(graph, stage.stage):
                    return _StageExecution(None, diagnostics=("stage produced no model patch",))
                revision = graph.revision
            else:
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
            if missing_kinds:
                warnings.append(
                    f"{stage.stage.value}: missing required kinds: "
                    + ", ".join(kind.value for kind in missing_kinds)
                )
            stage_result = StageResult(
                stage.stage.value,
                "needs_review" if semantic_invalid or missing_kinds else "completed",
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
            )
            warnings.extend(response.open_questions)
            self.repository.update_step(
                Step(
                    run_id,
                    task.id,
                    StepStatus.COMPLETED.value,
                    1,
                    response.input_hash or context_hash,
                    response.patch.id if response.patch else None,
                    tuple(response.diagnostics),
                    response.output_hash,
                    response.provider_id or self._provider_id(),
                    response.model_id or self._model_id(),
                    task.prompt_template_id,
                    context_hash,
                    started,
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
                "stage": stage_result.stage,
                "status": stage_result.status,
                "revision": stage_result.revision,
                "entity_count": stage_result.entity_count,
                "relation_count": stage_result.relation_count,
                "assumptions": list(stage_result.assumptions),
                "open_questions": list(stage_result.open_questions),
                "diagnostics": list(stage_result.diagnostics),
                "decision_records": [dict(record) for record in stage_result.decision_records],
            })
            return _StageExecution(stage_result, tuple(warnings))
        except Exception as exc:
            return _StageExecution(None, diagnostics=(str(exc),))

    def _ensure_input(self, request: GenerateModelRequest) -> None:
        graph = self.repository.load_graph(request.project_id)
        text = " ".join(str(request.requirement_text or "").split()).strip()
        source_ids: tuple[str, ...] = ()
        if not text:
            list_regions = getattr(self.repository, "list_source_regions", None)
            if callable(list_regions):
                regions = tuple(list_regions(request.project_id, request.document_ids))
                text = "\n".join(
                    str(region.get("text", "")).strip()
                    for region in regions
                    if str(region.get("text", "")).strip()
                ).strip()
                source_ids = tuple(
                    dict.fromkeys(
                        str(region.get("id", "")).strip()
                        for region in regions
                        if str(region.get("id", "")).strip()
                    )
                )
        if text:
            existing = next(
                (
                    entity
                    for entity in graph.entities
                    if entity.kind is EntityKind.REQUIREMENT
                    and entity.meta.status is not EntityStatus.DEPRECATED
                    and str(entity.payload.get("statement", entity.meta.name)).strip() == text
                ),
                None,
            )
            if existing is None:
                entity = make_entity(
                    EntityKind.REQUIREMENT,
                    text,
                    {
                        "statement": text,
                        "source": "user_input",
                        "level": "system",
                        "type": "functional",
                        "obligation": "系统应",
                        "verification_method": "test",
                    },
                    status=EntityStatus.CANDIDATE,
                    producer=Producer.USER,
                    confidence=1.0,
                    source_ids=source_ids,
                    revision=graph.revision,
                )
                patch = Patch.create(
                    request.project_id,
                    "user.requirement_input",
                    (AddEntity(entity),),
                    "用户输入自然语言需求",
                    graph.revision,
                )
                self.repository.append_patch(request.project_id, patch, graph.revision)
            return
        if any(
            entity.kind is EntityKind.REQUIREMENT
            and entity.meta.status is not EntityStatus.DEPRECATED
            for entity in graph.entities
        ):
            return
        if request.document_ids or self.repository.has_documents(request.project_id):
            raise InputRequired("document input contains no readable requirement text")
        raise InputRequired("requirement_text or an existing requirement is required")

    def _context(self, graph, task_id: str, document_ids: tuple[str, ...]) -> ContextBundle:
        evidence = tuple(self.repository.list_evidence(graph.project_id))
        if document_ids:
            selected = set(document_ids)
            evidence = tuple(
                item for item in evidence
                if not selected or str(item.get("source_id", item.get("document_id", ""))) in selected
            )
        return ContextBundle(
            graph.project_id,
            task_id,
            graph.revision,
            tuple(
                entity for entity in graph.entities
                if entity.meta.status is not EntityStatus.DEPRECATED
            ),
            graph.relations,
            evidence,
        )

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
        )

    def _provider_id(self) -> str:
        return str(getattr(self.runtime_selection, "provider_id", "offline"))

    def _model_id(self) -> str:
        return str(getattr(self.runtime_selection, "model_id", "rule-runtime"))

    def _mode(self) -> str:
        return str(getattr(self.runtime_selection, "mode", "offline"))

    def _audit(self, project_id: str, kind: str, payload: Mapping[str, object]) -> None:
        recorder = getattr(self.repository, "record_audit", None)
        if recorder is not None:
            recorder(project_id, kind, payload)


_REANALYSIS_START = {
    EntityKind.SYSTEM: 0,
    EntityKind.STAKEHOLDER: 0,
    EntityKind.CONCERN: 0,
    EntityKind.LIFECYCLE_STAGE: 0,
    EntityKind.SCENARIO_HYPOTHESIS: 0,
    EntityKind.USE_CASE: 0,
    EntityKind.OPERATIONAL_SCENARIO: 0,
    EntityKind.ACTIVITY: 0,
    EntityKind.REQUIREMENT: 0,
    EntityKind.FUNCTION: 1,
    EntityKind.FUNCTIONAL_FLOW: 1,
    EntityKind.FUNCTIONAL_SCENARIO: 1,
    EntityKind.LOGICAL_COMPONENT: 2,
    EntityKind.INTERFACE: 2,
    EntityKind.STATE: 2,
    EntityKind.PHYSICAL_BLOCK: 3,
    EntityKind.HAZARD: 4,
    EntityKind.FAILURE_MODE: 4,
    EntityKind.VERIFICATION_CASE: 4,
    EntityKind.VALIDATION_CASE: 4,
    EntityKind.EVIDENCE: 4,
}


def _reanalysis_stages(kind: EntityKind):
    start = _REANALYSIS_START.get(kind, 0)
    return tuple(vertical_stage_specs())[start:]


def _reanalysis_payload(result: GenerateModelResult, entity_id: str, trigger_revision: int, stages, *, execution_status: str):
    payload = dict(result.as_dict())
    payload.update({
        "entity_id": entity_id,
        "trigger_revision": trigger_revision,
        "selected_stages": [stage.stage.value for stage in stages],
        "execution_status": execution_status,
        "execution_status_label": "重新分析已完成" if execution_status == "completed" else "重新分析失败",
    })
    return payload


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


def _targets(graph, source_id: str, predicate: RelationPredicate) -> tuple[str, ...]:
    return tuple(
        relation.target_id
        for relation in graph.relations
        if relation.source_id == source_id and relation.predicate is predicate
    )


_TRACE_READY_STATUSES = frozenset({
    EntityStatus.VALIDATED,
    EntityStatus.ACCEPTED,
    EntityStatus.LOCKED,
})


def _trace_targets(graph, source_id: str, predicate: RelationPredicate, kind: EntityKind) -> tuple[str, ...]:
    index = graph.entity_index
    return tuple(sorted({
        relation.target_id
        for relation in graph.relations
        if relation.source_id == source_id
        and relation.predicate is predicate
        and index.get(relation.target_id) is not None
        and index[relation.target_id].kind is kind
        and index[relation.target_id].meta.status in _TRACE_READY_STATUSES
    }))


def build_traceability_summary(graph) -> TraceabilitySummary:
    active = [
        entity for entity in graph.entities
        if entity.kind is EntityKind.REQUIREMENT
        and entity.meta.status is not EntityStatus.DEPRECATED
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
        functions = _trace_targets(graph, requirement.id, RelationPredicate.SATISFIED_BY, EntityKind.FUNCTION)
        logical = tuple(dict.fromkeys(
            logical_id
            for function_id in functions
            for logical_id in _trace_targets(graph, function_id, RelationPredicate.ALLOCATED_TO, EntityKind.LOGICAL_COMPONENT)
        ))
        physical = tuple(dict.fromkeys(
            physical_id
            for logical_id in logical
            for physical_id in _trace_targets(graph, logical_id, RelationPredicate.ALLOCATED_TO, EntityKind.PHYSICAL_BLOCK)
        ))
        verification = _trace_targets(graph, requirement.id, RelationPredicate.VERIFIED_BY, EntityKind.VERIFICATION_CASE)
        validation = _trace_targets(graph, requirement.id, RelationPredicate.VALIDATED_BY, EntityKind.VALIDATION_CASE)
        rflp = bool(functions and logical and physical)
        if rflp:
            rflp_complete += 1
        elif functions or logical or physical:
            rflp_partial += 1
        else:
            rflp_missing += 1
        verification_complete += bool(verification)
        validation_complete += bool(validation)
        end_to_end = rflp and bool(verification) and bool(validation)
        if end_to_end:
            end_to_end_complete += 1
        elif rflp or verification or validation:
            end_to_end_partial += 1
        else:
            end_to_end_missing += 1
        path = tuple(
            item for item in (
                requirement.id,
                *(functions[:1]),
                *(logical[:1]),
                *(physical[:1]),
                *(verification[:1]),
                *(validation[:1]),
            ) if item
        )
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
