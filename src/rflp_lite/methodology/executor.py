"""Execution of one TaskSpec under its declared contract."""

from __future__ import annotations

from collections.abc import Mapping
import json
from dataclasses import replace

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import (
    AdapterFailure,
    ContractViolation,
    ProposalCompileFailure,
    StructuredOutputFailure,
    TransportFailure,
)
from rflp_lite.domain.entities import EntityKind, EntityStatus
from rflp_lite.domain.model import Patch
from rflp_lite.methodology.contracts import (
    ContextBundle, FailureStage, StepStatus, TaskExecutionRequest, TaskExecutionResponse, TaskRuntime, TaskSpec,
)
from rflp_lite.methodology.registries import PromptRegistry, RetryPolicy, SchemaRegistry, ValidatorRegistry
from rflp_lite.methodology.tasks import output_contract
from rflp_lite.methodology.validators import default_validators


def _request_task(task: TaskSpec) -> TaskSpec:
    """Make vertical updates semantic-only; runtime owns lifecycle status."""

    if not task.id.startswith("vertical."):
        return task
    return replace(
        task,
        patch_policy=replace(
            task.patch_policy,
            writable_fields=frozenset(
                field for field in task.patch_policy.writable_fields
                if field != "status"
            ),
        ),
    )


class TaskExecutor:
    def __init__(
        self,
        runtime: TaskRuntime,
        *,
        prompt_registry: PromptRegistry | None = None,
        schema_registry: SchemaRegistry | None = None,
        validator_registry: ValidatorRegistry | None = None,
    ) -> None:
        self.runtime = runtime
        self.prompts = prompt_registry or PromptRegistry()
        self.schemas = schema_registry or SchemaRegistry()
        self.validators = validator_registry or ValidatorRegistry(default_validators())

    def request(
        self,
        task: TaskSpec,
        context: ContextBundle,
        methodology_version: str,
        evidence_bundle: tuple[dict[str, object], ...] | None = None,
        token_budget: int = 2000,
    ) -> TaskExecutionRequest:
        request_task = _request_task(task)
        contract = output_contract(request_task)
        contract = _contextualize_contract(task, context, contract)
        self.schemas.register(task.output_schema_id, contract)
        prompt = self.prompts.resolve(task.prompt_template_id)
        contract = {
            **contract,
            "prompt_template_id": task.prompt_template_id,
            "prompt_version": prompt.version,
            "prompt_hash": prompt.prompt_hash,
            "validators": list(task.validators),
            "max_attempts": task.max_attempts,
        }
        return TaskExecutionRequest(
            task.id,
            methodology_version,
            context,
            evidence_bundle if evidence_bundle is not None else context.evidence,
            contract,
            token_budget,
            task.tools,
            task.prompt_template_id,
            task.validators,
            task.max_attempts,
            request_task.patch_policy,
            prompt.text,
            prompt.version,
            prompt.prompt_hash,
        )


    def execute(
        self,
        task: TaskSpec,
        context: ContextBundle,
        methodology_version: str = "v2.0",
        *,
        evidence_bundle: tuple[dict[str, object], ...] | None = None,
        token_budget: int = 2000,
        retry_policy: RetryPolicy | None = None,
    ) -> TaskExecutionResponse:
        request = self.request(task, context, methodology_version, evidence_bundle, token_budget)
        input_hash = canonical_hash({
            "task_id": task.id, "prompt_hash": request.prompt_hash,
            "context": context, "evidence": request.evidence_bundle,
            "contract": request.output_contract,
        })
        policy = retry_policy or RetryPolicy(task.max_attempts)
        diagnostics: list[str] = []
        last_response: TaskExecutionResponse | None = None
        last_failure_stage: FailureStage | None = None
        for attempt in range(1, policy.max_attempts + 1):
            try:
                response = self.runtime.execute(request)
                last_response = response
                last_failure_stage = response.failure_stage
                if response.patch is not None and response.status is not StepStatus.COMPLETED:
                    return replace(
                        response,
                        diagnostics=tuple(response.diagnostics) + (
                            "non-completed response cannot carry a committable patch",
                        ),
                        input_hash=response.input_hash or input_hash,
                        output_hash=response.output_hash or canonical_hash(response.patch),
                    )
                if response.status is StepStatus.COMPLETED:
                    return replace(
                        response,
                        input_hash=response.input_hash or input_hash,
                        output_hash=response.output_hash or canonical_hash(response.patch),
                        diagnostics=tuple(diagnostics) + tuple(response.diagnostics),
                    )
                diagnostics.extend(response.diagnostics or (f"attempt={attempt}: runtime returned {response.status.value}",))
                if response.failure_stage in {FailureStage.STRUCTURAL, FailureStage.COMPILER}:
                    return replace(
                        response,
                        input_hash=response.input_hash or input_hash,
                        output_hash=response.output_hash or canonical_hash(response.patch),
                        diagnostics=tuple(diagnostics),
                    )
            except Exception as exc:
                stage = _failure_stage(exc)
                last_failure_stage = stage
                diagnostics.append(_diagnostic(exc, attempt))
                if stage in {FailureStage.STRUCTURAL, FailureStage.COMPILER}:
                    return TaskExecutionResponse(
                        StepStatus.DEGRADED,
                        diagnostics=tuple(diagnostics),
                        input_hash=input_hash,
                        output_hash=canonical_hash(diagnostics),
                        provider_id=str(getattr(exc, "provider_id", "")),
                        model_id=str(getattr(exc, "model_id", "")),
                        failure_stage=stage,
                        finish_reason=str(getattr(exc, "finish_reason", "")),
                        usage=getattr(exc, "usage", {}),
                    )
        return TaskExecutionResponse(
            StepStatus.DEGRADED,
            diagnostics=tuple(diagnostics) or ("task execution failed",),
            input_hash=input_hash,
            output_hash=canonical_hash(last_response.patch if last_response else diagnostics),
            provider_id=last_response.provider_id if last_response else "",
            model_id=last_response.model_id if last_response else "",
            failure_stage=(last_response.failure_stage or last_failure_stage) if last_response else last_failure_stage,
        )

    def validate_response(self, project_id, task, graph, context, response) -> None:
        """Run the same methodology validators for any runtime before CAS."""

        from rflp_lite.methodology.validation import ValidationContext

        self.validators.validate(
            task.validators,
            context=ValidationContext(project_id, task, graph, context, response),
        )


def _require_mapping(value: object) -> None:
    if value is None or isinstance(value, (dict, Patch)):
        return
    if not isinstance(value, dict):
        raise ContractViolation("task result is not serializable")


def _contextualize_contract(
    task: TaskSpec,
    context: ContextBundle,
    contract: Mapping[str, object],
) -> Mapping[str, object]:
    """Add state-dependent constraints to contracts with identity branches."""

    if task.id == "vertical.requirements":
        contract = _contextualize_vertical_requirements(context, contract)
    if task.id != "system_definition":
        contract = _contextualize_stakeholder_requirements(task, context, contract)
        return _contextualize_lifecycle_analysis(task, context, contract)
    active_systems = tuple(
        entity for entity in context.entities
        if entity.kind is EntityKind.SYSTEM and entity.meta.status is not EntityStatus.DEPRECATED
    )
    properties = dict(contract["properties"])
    entities_schema = dict(properties["entities"])
    updates_schema = dict(properties["updates"])
    deprecations_schema = dict(properties["deprecations"])
    if len(active_systems) == 1:
        entities_schema["maxItems"] = 0
        updates_schema.update({"minItems": 1, "maxItems": 1})
        update_item = dict(updates_schema["items"])
        update_properties = dict(update_item["properties"])
        update_properties["entity_id"] = {"const": active_systems[0].id}
        field_patch = dict(update_properties["field_patch"])
        field_patch["required"] = ["payload"]
        update_properties["field_patch"] = field_patch
        update_item["properties"] = update_properties
        updates_schema["items"] = update_item
    elif not active_systems:
        entities_schema.update({"minItems": 1, "maxItems": 1})
        updates_schema["maxItems"] = 0
    else:
        entities_schema["maxItems"] = 0
        updates_schema["maxItems"] = 0
    deprecations_schema["maxItems"] = 0
    properties.update({
        "entities": entities_schema,
        "updates": updates_schema,
        "deprecations": deprecations_schema,
    })
    return {**contract, "properties": properties}


def _contextualize_stakeholder_requirements(
    task: TaskSpec,
    context: ContextBundle,
    contract: Mapping[str, object],
) -> Mapping[str, object]:
    """Prevent duplicate requirement creation when source requirements exist."""

    if task.id != "stakeholder_requirements":
        return contract
    existing_requirements = tuple(
        entity for entity in context.entities
        if entity.kind is EntityKind.REQUIREMENT and entity.meta.status is not EntityStatus.DEPRECATED
    )
    if not existing_requirements:
        return contract
    properties = dict(contract["properties"])
    source_concerns = tuple(
        entity for entity in context.entities
        if entity.kind is EntityKind.CONCERN
        and entity.meta.status is not EntityStatus.DEPRECATED
    )
    source_stakeholders = tuple(
        entity for entity in context.entities
        if entity.kind is EntityKind.STAKEHOLDER
        and entity.meta.status is not EntityStatus.DEPRECATED
    )
    # When concerns are present they may represent newly discovered needs that
    # do not match imported requirements, so the model must retain the add path.
    # Only the stakeholder fallback is forced to reuse existing requirements.
    if not source_concerns:
        entities_schema = dict(properties["entities"])
        entities_schema["maxItems"] = 0
        properties["entities"] = entities_schema
    if source_concerns or source_stakeholders:
        relations_schema = dict(properties["relations"])
        relations_schema["minItems"] = 1
        properties["relations"] = relations_schema
    return {**contract, "properties": properties}


def _contextualize_lifecycle_analysis(
    task: TaskSpec,
    context: ContextBundle,
    contract: Mapping[str, object],
) -> Mapping[str, object]:
    """Reuse imported lifecycle stages and reserve additions for transitions."""

    if task.id != "lifecycle_analysis":
        return contract
    existing_stages = tuple(
        entity for entity in context.entities
        if entity.kind is EntityKind.LIFECYCLE_STAGE
        and entity.meta.status is not EntityStatus.DEPRECATED
    )
    if not existing_stages:
        return contract
    properties = dict(contract["properties"])
    entities_schema = dict(properties["entities"])
    entity_item = dict(entities_schema["items"])
    entity_properties = dict(entity_item["properties"])
    entity_properties["kind"] = {"const": EntityKind.LIFECYCLE_TRANSITION.value}
    entity_item["properties"] = entity_properties
    entities_schema["items"] = entity_item
    properties["entities"] = entities_schema
    return {**contract, "properties": properties}


def _contextualize_vertical_requirements(
    context: ContextBundle,
    contract: Mapping[str, object],
) -> Mapping[str, object]:
    """Make the vertical R call an incremental closure when the graph has R data."""

    active_kinds = {
        entity.kind
        for entity in context.entities
        if entity.meta.status not in {EntityStatus.REJECTED, EntityStatus.DEPRECATED}
    }
    if not active_kinds:
        return contract
    properties = dict(contract["properties"])
    entities_schema = dict(properties["entities"])
    entity_item = dict(entities_schema["items"])
    entity_properties = dict(entity_item["properties"])
    stage_kinds = {
        EntityKind.SYSTEM,
        EntityKind.STAKEHOLDER,
        EntityKind.CONCERN,
        EntityKind.LIFECYCLE_STAGE,
        EntityKind.LIFECYCLE_TRANSITION,
        EntityKind.SCENARIO_HYPOTHESIS,
        EntityKind.USE_CASE,
        EntityKind.OPERATIONAL_SCENARIO,
        EntityKind.ACTIVITY,
        EntityKind.REQUIREMENT,
    }
    missing_kinds = tuple(
        kind.value
        for kind in sorted(stage_kinds - active_kinds, key=lambda item: item.value)
    )
    entity_properties["kind"] = {"enum": list(missing_kinds)}
    entity_item["properties"] = entity_properties
    entities_schema["items"] = entity_item
    entities_schema["maxItems"] = len(missing_kinds)
    properties["entities"] = entities_schema
    deprecations_schema = dict(properties["deprecations"])
    deprecations_schema["maxItems"] = 0
    properties["deprecations"] = deprecations_schema
    return {**contract, "properties": properties}


def _failure_stage(exc: Exception) -> FailureStage | None:
    if isinstance(exc, StructuredOutputFailure):
        return FailureStage.STRUCTURAL
    if isinstance(exc, ProposalCompileFailure):
        return FailureStage.COMPILER
    if isinstance(exc, (TransportFailure, AdapterFailure)):
        return FailureStage.TRANSPORT
    return None


def _diagnostic(exc: Exception, attempt: int) -> str:
    payload: dict[str, object] = {
        "attempt": attempt,
        # Keep the actionable failure before the potentially large response
        # excerpts in sorted JSON diagnostics.
        "error": str(exc),
        "message": str(exc),
    }
    if isinstance(exc, (StructuredOutputFailure, ProposalCompileFailure, TransportFailure)):
        payload.update({
            "stage": exc.stage,
            "code": exc.code,
        })
    if isinstance(exc, (StructuredOutputFailure, ProposalCompileFailure, TransportFailure)):
        payload.update({
            **_response_evidence("raw_response", exc.raw_response),
            **_response_evidence("initial_raw_response", exc.initial_raw_response),
            "schema_hash": exc.schema_hash,
            "retry_count": exc.retry_count,
            "provider_id": exc.provider_id,
            "model_id": exc.model_id,
            "finish_reason": getattr(exc, "finish_reason", ""),
            "usage": getattr(exc, "usage", {}),
        })
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _response_evidence(prefix: str, value: object, *, excerpt_limit: int = 2000) -> dict[str, object]:
    text = str(value or "")
    return {
        f"{prefix}_excerpt": text[:excerpt_limit],
        f"{prefix}_hash": canonical_hash(text),
        f"{prefix}_size": len(text),
    }
