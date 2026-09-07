"""Adapter from TaskExecutionRequest to the existing GenerationRequest port."""

from __future__ import annotations

from typing import Mapping

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.methodology.contracts import StepStatus, TaskExecutionRequest, TaskExecutionResponse
from rflp_lite.methodology.patches import patch_from_response
from rflp_lite.ports.generative_model import GenerationRequest, GenerativeModel


class StructuredModelRuntime:
    def __init__(self, model: GenerativeModel):
        self.model = model

    def execute(self, request: TaskExecutionRequest) -> TaskExecutionResponse:
        payload: dict[str, object] = {
            "task_id": request.task_id,
            "methodology_version": request.methodology_version,
            "context": {
                "project_id": request.context_bundle.project_id,
                "revision": request.context_bundle.revision,
                "entities": [item.as_dict() for item in request.context_bundle.entities],
                "relations": [str(item) for item in request.context_bundle.relations],
            },
            "evidence": list(request.evidence_bundle),
            "context_hash": canonical_hash(request.context_bundle),
        }
        contract = _output_schema(request.output_contract)
        response = self.model.complete_json(
            GenerationRequest(
                request.task_id,
                "只完成当前 TaskSpec。仅返回 operations/reason JSON 对象；不要解释，不要输出未授权类型或关系。",
                payload,
                contract,
                request.token_budget,
            )
        )
        try:
            patch = patch_from_response(request, response.payload)
        except (TypeError, ValueError, KeyError) as exc:
            raise ContractViolation(f"task output cannot become a Patch: {exc}") from exc
        return TaskExecutionResponse(
            StepStatus.COMPLETED,
            patch=patch,
            diagnostics=(f"provider={response.provider_id}", f"output_hash={response.output_hash}"),
            repaired=response.repaired,
            input_hash=response.input_hash,
            output_hash=response.output_hash,
            provider_id=response.provider_id,
            model_id=response.model_id,
        )


def _output_schema(contract: Mapping[str, object]) -> dict[str, object]:
    """Use a real JSON Schema while keeping TaskSpec contracts serializable."""

    schema = contract.get("schema")
    if isinstance(schema, Mapping):
        return dict(schema)
    if contract.get("type") == "object" and isinstance(contract.get("properties"), Mapping):
        return {key: value for key, value in contract.items() if key in {"type", "additionalProperties", "required", "properties"}}
    output_kinds = contract.get("output_kinds", ())
    kind_values = [str(value) for value in output_kinds]
    # This mirrors methodology.tasks.output_contract without making the
    # runtime import a TaskSpec or a provider-specific schema registry.
    operation = {
        "type": "object",
        "additionalProperties": False,
        "required": ["op"],
        "properties": {
            "op": {"enum": ["ADD", "UPDATE", "RELATE", "DEPRECATE"]},
            "kind": {"enum": kind_values},
            "name": {"type": "string", "minLength": 1},
            "entity_id": {"type": "string"},
            "source_id": {"type": "string"},
            "target_id": {"type": "string"},
            "predicate": {"type": "string"},
            "payload": {"type": "object"},
            "field_patch": {"type": "object"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "source_ids": {"type": "array", "items": {"type": "string"}},
            "lifecycle_ids": {"type": "array", "items": {"type": "string"}},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["operations"],
        "properties": {
            "operations": {"type": "array", "items": operation, "maxItems": 32},
            "reason": {"type": "string", "maxLength": 300},
        },
    }
