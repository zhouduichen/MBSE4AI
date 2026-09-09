"""Execution of one TaskSpec under its declared contract."""

from __future__ import annotations

from dataclasses import replace

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.domain.model import Patch
from rflp_lite.methodology.contracts import (
    ContextBundle, StepStatus, TaskExecutionRequest, TaskExecutionResponse, TaskRuntime, TaskSpec,
)
from rflp_lite.methodology.registries import PromptRegistry, RetryPolicy, SchemaRegistry, ValidatorRegistry
from rflp_lite.methodology.tasks import output_contract


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
        self.validators = validator_registry or ValidatorRegistry({
            "schema": lambda value: _require_mapping(value),
            "identity": lambda value: None,
            "reference": lambda value: None,
        })

    def request(
        self,
        task: TaskSpec,
        context: ContextBundle,
        methodology_version: str,
        evidence_bundle: tuple[dict[str, object], ...] | None = None,
        token_budget: int = 2000,
    ) -> TaskExecutionRequest:
        contract = output_contract(task)
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
            task.patch_policy,
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
        for attempt in range(1, policy.max_attempts + 1):
            try:
                response = self.runtime.execute(request)
                last_response = response
                if response.status is StepStatus.COMPLETED:
                    self.validators.validate(task.validators, response.patch or {})
                    return replace(
                        response,
                        input_hash=response.input_hash or input_hash,
                        output_hash=response.output_hash or canonical_hash(response.patch),
                        diagnostics=tuple(diagnostics) + tuple(response.diagnostics),
                    )
                diagnostics.extend(response.diagnostics or (f"attempt={attempt}: runtime returned {response.status.value}",))
            except Exception as exc:
                diagnostics.append(f"attempt={attempt}: {exc}")
        return TaskExecutionResponse(
            StepStatus.DEGRADED,
            diagnostics=tuple(diagnostics) or ("task execution failed",),
            input_hash=input_hash,
            output_hash=canonical_hash(last_response.patch if last_response else diagnostics),
            provider_id=last_response.provider_id if last_response else "",
            model_id=last_response.model_id if last_response else "",
        )


def _require_mapping(value: object) -> None:
    if value is None or isinstance(value, (dict, Patch)):
        return
    if not isinstance(value, dict):
        raise ContractViolation("task result is not serializable")
