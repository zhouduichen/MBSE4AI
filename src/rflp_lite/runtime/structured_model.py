"""Adapter from TaskExecutionRequest to the existing GenerationRequest port."""

from __future__ import annotations

import json
from typing import Mapping

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import ContractViolation, ProposalCompileFailure
from rflp_lite.methodology.contracts import StepStatus, TaskExecutionRequest, TaskExecutionResponse
from rflp_lite.methodology.proposal_compiler import compile_task_proposal, parse_task_proposal
from rflp_lite.ports.generative_model import GenerationRequest, GenerativeModel
from rflp_lite.runtime.lifecycle_rule import LIFECYCLE_TASKS


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
                "relations": [
                    {
                        "id": item.id,
                        "source_id": item.source_id,
                        "predicate": item.predicate.value,
                        "target_id": item.target_id,
                        "evidence_ids": list(item.evidence_ids),
                    }
                    for item in request.context_bundle.relations
                ],
            },
            "evidence": list(request.evidence_bundle),
            "controller_decisions": [
                dict(item) for item in request.context_bundle.controller_decisions
            ],
            "methodology_guidance": dict(
                request.context_bundle.methodology_guidance
            ),
            "context_hash": canonical_hash(request.context_bundle),
        }
        contract = _output_schema(request.output_contract)
        response = self.model.complete_json(
            GenerationRequest(
                request.task_id,
                (
                    request.prompt_text
                    + "\n\n"
                    "仅返回 TaskProposal JSON 对象，必须包含 entities、relations、updates、deprecations、reason；"
                    "除非任务明确要求修改或弃用既有实体，否则 updates 和 deprecations 必须为空数组；"
                    "每个 entities[i].local_ref 必须在当前 Proposal 内唯一；local_ref 只是本轮临时引用，不是领域 ID；"
                    "relations 只能引用当前上下文中的 canonical entity id 或本 Proposal 内唯一的 local_ref；"
                    "读取 methodology_guidance 中的确定性检查结果，优先补齐其指出的当前阶段缺口；不要把 guidance 当作新的实体事实；"
                    "不要返回 operations、Patch ID、revision、status、producer 或 kind/value/path 更新 DSL；不要解释。"
                ),
                payload,
                contract,
                request.token_budget,
            )
        )
        try:
            proposal = parse_task_proposal(request, response.payload)
            patch = compile_task_proposal(request, response.payload)
        except ContractViolation as exc:
            raise ProposalCompileFailure(
                str(exc),
                raw_response=json.dumps(response.payload, ensure_ascii=False, sort_keys=True),
                schema_hash=canonical_hash(contract),
                provider_id=response.provider_id,
                model_id=response.model_id,
                finish_reason=response.finish_reason,
                usage=response.usage,
            ) from exc
        diagnostics = [
            f"provider={response.provider_id}",
            f"output_hash={response.output_hash}",
        ]
        if response.finish_reason:
            diagnostics.append(f"finish_reason={response.finish_reason}")
        if response.usage:
            diagnostics.append(
                "usage=" + json.dumps(response.usage, ensure_ascii=False, sort_keys=True)
            )
        if request.task_id in LIFECYCLE_TASKS:
            diagnostics.append("lifecycle:structured")
        return TaskExecutionResponse(
            StepStatus.COMPLETED,
            patch=patch,
            diagnostics=tuple(diagnostics),
            repaired=response.repaired,
            input_hash=response.input_hash,
            output_hash=response.output_hash,
            provider_id=response.provider_id,
            model_id=response.model_id,
            finish_reason=response.finish_reason,
            usage=response.usage,
            assumptions=proposal.assumptions,
            open_questions=proposal.open_questions,
            decision_records=proposal.decision_records,
        )


def _output_schema(contract: Mapping[str, object]) -> dict[str, object]:
    """Extract the canonical TaskProposal JSON Schema from a TaskSpec contract."""

    schema = contract.get("schema")
    if isinstance(schema, Mapping):
        return dict(schema)
    if contract.get("type") == "object" and isinstance(contract.get("properties"), Mapping):
        proposal_fields = {"entities", "relations", "updates", "deprecations", "reason"}
        if proposal_fields <= set(contract["properties"]):
            return {
                key: value
                for key, value in contract.items()
                if key in {"type", "additionalProperties", "required", "properties"}
            }
    raise ContractViolation("TaskProposal schema is required; Patch operations are not accepted")
