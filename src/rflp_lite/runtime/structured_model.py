"""Adapter from TaskExecutionRequest to the existing GenerationRequest port."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Mapping

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.entities import EntityKind, EntityStatus
from rflp_lite.domain.errors import ContractViolation, ProposalCompileFailure
from rflp_lite.domain.model import AddEntity, Deprecate, Patch, Relate, UpdateEntity
from rflp_lite.methodology.contracts import StepStatus, TaskExecutionRequest, TaskExecutionResponse
from rflp_lite.methodology.proposal_compiler import (
    TaskProposal,
    compile_task_proposal,
    parse_task_proposal,
)
from rflp_lite.ports.generative_model import (
    GenerationRequest,
    GenerationResponse,
    GenerativeModel,
)
from rflp_lite.runtime.lifecycle_rule import LIFECYCLE_TASKS


_VV_BATCH_TASK = "vertical.verification_validation"
_VERTICAL_BATCH_TASKS = frozenset({
    "vertical.functional",
    "vertical.logical",
    "vertical.physical",
    _VV_BATCH_TASK,
})
_VERTICAL_BATCH_THRESHOLD = 3
_VERTICAL_BATCH_SIZE = 2


@dataclass(frozen=True, slots=True)
class _CompiledProposal:
    response: GenerationResponse
    proposal: TaskProposal
    patch: Patch | None
    compiler_repaired: bool = False


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
                "token_estimate": request.context_bundle.token_estimate,
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
        if request.task_id.startswith("vertical."):
            payload["requirement_worklist"] = _requirement_worklist(
                request.context_bundle
            )
        contract = _output_schema(request.output_contract)
        batches = _requirement_batches(
            request,
            payload.get("requirement_worklist", []),
            self.model,
        )
        compiled = tuple(
            self._complete_batch(
                request,
                contract,
                {
                    **payload,
                    **(
                        {"requirement_worklist": list(batch)}
                        if "requirement_worklist" in payload
                        else {}
                    ),
                    **(
                        {
                            "requirement_batch": {
                                "index": index,
                                "count": len(batches),
                                "is_first": index == 1,
                            }
                        }
                        if len(batches) > 1
                        else {}
                    ),
                },
            )
            for index, batch in enumerate(batches, start=1)
        )
        response, proposal, patch, compiler_repaired = _merge_compiled(
            request, compiled
        )
        diagnostics = [
            f"provider={response.provider_id}",
            f"output_hash={response.output_hash}",
        ]
        if compiler_repaired:
            diagnostics.append("compiler:repaired")
        if response.finish_reason:
            diagnostics.append(f"finish_reason={response.finish_reason}")
        if response.usage:
            diagnostics.append(
                "usage=" + json.dumps(response.usage, ensure_ascii=False, sort_keys=True)
            )
        if len(compiled) > 1:
            diagnostics.append(f"batch_count={len(compiled)}")
            diagnostics.extend(
                f"batch={index}/{len(compiled)}"
                for index in range(1, len(compiled) + 1)
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

    def _complete_batch(
        self,
        request: TaskExecutionRequest,
        contract: Mapping[str, object],
        payload: Mapping[str, object],
    ) -> _CompiledProposal:
        batch_instruction = _batch_instruction(
            request.task_id,
            payload.get("requirement_batch"),
        )
        response = self.model.complete_json(
            GenerationRequest(
                request.task_id,
                _structured_prompt(request.prompt_text, batch_instruction),
                payload,
                contract,
                request.token_budget,
            )
        )
        compiler_repaired = False
        try:
            proposal = parse_task_proposal(request, response.payload)
            patch = compile_task_proposal(request, response.payload)
        except ContractViolation as first_error:
            repair_payload = {
                **payload,
                "compiler_feedback": {
                    "error": str(first_error),
                    "invalid_proposal": response.payload,
                },
            }
            repair_response = self.model.complete_json(
                GenerationRequest(
                    request.task_id,
                    _compiler_repair_prompt(
                        request.prompt_text + batch_instruction, first_error
                    ),
                    repair_payload,
                    contract,
                    request.token_budget,
                )
            )
            try:
                proposal = parse_task_proposal(request, repair_response.payload)
                patch = compile_task_proposal(request, repair_response.payload)
            except ContractViolation as second_error:
                raise ProposalCompileFailure(
                    str(second_error),
                    raw_response=json.dumps(
                        repair_response.payload,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    initial_raw_response=json.dumps(
                        response.payload,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    schema_hash=canonical_hash(contract),
                    retry_count=1,
                    provider_id=repair_response.provider_id or response.provider_id,
                    model_id=repair_response.model_id or response.model_id,
                    finish_reason=repair_response.finish_reason,
                    usage=repair_response.usage,
                ) from second_error
            response = replace(repair_response, repaired=True)
            compiler_repaired = True
        return _CompiledProposal(response, proposal, patch, compiler_repaired)

_STRUCTURED_RULES = (
    "仅返回 TaskProposal JSON 对象，必须包含 entities、relations、updates、deprecations、reason；"
    "除非任务明确要求修改或弃用既有实体，否则 updates 和 deprecations 必须为空数组；"
    "每个 entities[i].local_ref 必须在当前 Proposal 内唯一；local_ref 只是本轮临时引用，不是领域 ID；"
    "relations 只能引用当前上下文中的 canonical entity id 或本 Proposal 内唯一的 local_ref；"
    "读取 methodology_guidance 中的确定性检查结果，优先补齐其指出的当前阶段缺口；不要把 guidance 当作新的实体事实；"
    "如果 methodology_guidance.stage_contract 存在，必须按其中的 reasoning_tasks 完成当前阶段，并遵守 required_kinds 与 allowed_predicates；"
    "如果 stage_completion.requirement_coverage.passed 为 false，必须优先修复其中列出的 missing_requirement_ids 和 coverage gap；"
    "如果 requirement_worklist 非空，必须逐条覆盖其中每个 requirement_id；不得把多条 Requirement 合并成一个无法追溯的下游对象；"
    "requirement_worklist.current 是已有的 canonical 追溯对象；优先复用其中的 ID，只修复 missing 列出的当前阶段缺口；"
    "如果 worklist item 含 available_current 和 unavailable_current，只能引用 available_current 中且确实存在于 context.entities 的 ID；"
    "unavailable_current 仅表示完整图中的延后追溯，不能引用、更新或声称本轮已经修复；无法在当前上下文完成的部分写入 open_questions；"
    "如果 requirement_worklist.truncated 为 true，只处理 items 中明确提供且在 context 中可见的 Requirement，不得声称已覆盖 omitted_requirement_ids；"
    "复用已有 Requirement、Function、LogicalComponent、PhysicalBlock 和 V&V Case 的 canonical id，只补缺失的 typed 实体或关系；"
    "无法由当前上下文证明的缺口写入 open_questions，不得把不完整覆盖声称为完成；"
    "不要返回 operations、Patch ID、revision、status、producer 或 kind/value/path 更新 DSL；不要解释。"
)


def _structured_prompt(prompt: str, batch_instruction: str = "") -> str:
    return f"{str(prompt).strip()}\n\n{_STRUCTURED_RULES}{batch_instruction}"


def _batch_instruction(task_id: str, meta: object) -> str:
    if not isinstance(meta, Mapping):
        return ""
    index = meta.get("index")
    count = meta.get("count")
    if task_id != _VV_BATCH_TASK:
        return (
            f"当前是 {task_id} 第 {index}/{count} 个需求批次。"
            "只处理 requirement_worklist 中的 canonical Requirement；"
            "不得为其它批次需求新增实体或更新，也不要把本批缺口合并成无法追溯的对象。"
        )
    is_first = bool(meta.get("is_first"))
    risk_instruction = (
        "本批可以生成一个代表当前上下文异常分支的 hazard 和 failure_mode；"
        if is_first
        else "本批不得新增 hazard 或 failure_mode，只生成本批需求的 VerificationCase、ValidationCase 和必要更新；"
    )
    return (
        f"当前是 V&V 第 {index}/{count} 个需求批次。"
        "只处理 requirement_worklist 中的 canonical Requirement；不得为其它批次需求重复生成 V&V Case。"
        + risk_instruction
    )


def _requirement_batches(
    request: TaskExecutionRequest,
    worklist: object,
    model: GenerativeModel,
) -> tuple[tuple[Mapping[str, object], ...], ...]:
    if not isinstance(worklist, (list, tuple)):
        return ((),)
    entries = tuple(item for item in worklist if isinstance(item, Mapping))
    if not (
        request.task_id in _VERTICAL_BATCH_TASKS
        and len(entries) > _VERTICAL_BATCH_THRESHOLD
        and getattr(model, "supports_requirement_batching", False) is True
    ):
        return (entries,)
    return tuple(
        entries[start : start + _VERTICAL_BATCH_SIZE]
        for start in range(0, len(entries), _VERTICAL_BATCH_SIZE)
    )


def _merge_compiled(
    request: TaskExecutionRequest,
    compiled: tuple[_CompiledProposal, ...],
) -> tuple[GenerationResponse, TaskProposal, Patch | None, bool]:
    if len(compiled) == 1:
        item = compiled[0]
        return item.response, item.proposal, item.patch, item.compiler_repaired

    operations = _merge_operations(request, compiled)
    proposals = tuple(item.proposal for item in compiled)
    merged_proposal = TaskProposal(
        tuple(entity for proposal in proposals for entity in proposal.entities),
        tuple(relation for proposal in proposals for relation in proposal.relations),
        tuple(update for proposal in proposals for update in proposal.updates),
        tuple(deprecation for proposal in proposals for deprecation in proposal.deprecations),
        "按需求批次合并 V&V 结构化 Proposal",
        _stable_unique(
            value for proposal in proposals for value in proposal.assumptions
        ),
        _stable_unique(
            value for proposal in proposals for value in proposal.open_questions
        ),
        _stable_unique_mappings(
            value for proposal in proposals for value in proposal.decision_records
        ),
    )
    first = compiled[0].response
    merged_response = GenerationResponse(
        first.lens_id,
        _merge_payloads(compiled),
        canonical_hash(tuple(item.response.input_hash for item in compiled)),
        canonical_hash(tuple(item.response.output_hash for item in compiled)),
        any(item.response.repaired for item in compiled),
        first.provider_id,
        first.model_id,
        first.template_version,
        sum(item.response.duration_ms for item in compiled),
        first.status,
        first.finish_reason,
        _merge_usage(item.response.usage for item in compiled),
    )
    return (
        merged_response,
        merged_proposal,
        Patch.create(
            request.context_bundle.project_id,
            request.task_id,
            operations,
            merged_proposal.reason,
            request.context_bundle.revision,
        )
        if operations
        else None,
        any(item.compiler_repaired for item in compiled),
    )


def _merge_operations(
    request: TaskExecutionRequest,
    compiled: tuple[_CompiledProposal, ...],
) -> tuple[object, ...]:
    patches = tuple(item.patch for item in compiled)
    later_risk_ids = {
        operation.entity.id
        for patch in patches[1:]
        if patch is not None
        for operation in patch.operations
        if isinstance(operation, AddEntity)
        and operation.entity.kind in {EntityKind.HAZARD, EntityKind.FAILURE_MODE}
    }
    merged: list[object] = []
    seen: set[tuple[object, ...]] = set()
    for batch_index, patch in enumerate(patches):
        if patch is None:
            continue
        for operation in patch.operations:
            if (
                batch_index > 0
                and isinstance(operation, AddEntity)
                and operation.entity.kind in {EntityKind.HAZARD, EntityKind.FAILURE_MODE}
            ):
                continue
            if batch_index > 0 and isinstance(operation, Relate) and (
                operation.source_id in later_risk_ids
                or operation.target_id in later_risk_ids
            ):
                continue
            key = _operation_key(operation)
            if key in seen:
                continue
            seen.add(key)
            merged.append(operation)
    maximum = request.patch_policy.max_operations
    if maximum is None and request.task_id == _VV_BATCH_TASK:
        maximum = 32
    if maximum is not None and len(merged) > maximum:
        raise ProposalCompileFailure(
            f"merged V&V batch proposal exceeds operation limit: {maximum}",
            code="batch_operation_limit",
            raw_response=json.dumps(
                [item.response.payload for item in compiled],
                ensure_ascii=False,
                sort_keys=True,
            ),
            schema_hash=canonical_hash(request.output_contract),
            provider_id=compiled[0].response.provider_id,
            model_id=compiled[0].response.model_id,
        )
    return tuple(merged)


def _operation_key(operation: object) -> tuple[object, ...]:
    if isinstance(operation, AddEntity):
        return ("add", operation.entity.id)
    if isinstance(operation, Relate):
        return (
            "relate",
            operation.source_id,
            operation.predicate.value,
            operation.target_id,
            operation.evidence_ids,
        )
    if isinstance(operation, UpdateEntity):
        return (
            "update",
            operation.entity_id,
            canonical_hash(operation.field_patch),
        )
    if isinstance(operation, Deprecate):
        return ("deprecate", operation.entity_id)
    return (type(operation).__name__, repr(operation))


def _merge_payloads(compiled: tuple[_CompiledProposal, ...]) -> dict:
    list_fields = (
        "entities",
        "relations",
        "updates",
        "deprecations",
        "assumptions",
        "open_questions",
        "decision_records",
    )
    merged = {
        field: [
            value
            for item in compiled
            for value in item.response.payload.get(field, [])
            if isinstance(item.response.payload.get(field, []), list)
        ]
        for field in list_fields
    }
    reasons = [
        str(item.response.payload.get("reason", "")).strip()
        for item in compiled
        if str(item.response.payload.get("reason", "")).strip()
    ]
    merged["reason"] = "；".join(dict.fromkeys(reasons))[:300] or "合并 V&V Proposal"
    return merged


def _stable_unique(values) -> tuple[object, ...]:
    result: list[object] = []
    seen: set[str] = set()
    for value in values:
        marker = canonical_hash(value)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(value)
    return tuple(result)


def _stable_unique_mappings(values) -> tuple[Mapping[str, object], ...]:
    return tuple(
        value for value in _stable_unique(values) if isinstance(value, Mapping)
    )


def _merge_usage(values) -> Mapping[str, object]:
    usages = tuple(value for value in values if isinstance(value, Mapping))
    keys = {str(key) for usage in usages for key in usage}
    merged = {}
    for key in sorted(keys):
        items = [usage[key] for usage in usages if key in usage]
        if items and all(
            isinstance(item, (int, float)) and not isinstance(item, bool)
            for item in items
        ):
            merged[key] = sum(items)
        elif items:
            merged[key] = items[0]
    return merged


def _requirement_worklist(context) -> list[Mapping[str, object]]:
    """Expose a compact, canonical per-requirement worklist to vertical LLM calls."""

    gaps_by_requirement: dict[str, Mapping[str, object]] = {}
    guidance = context.methodology_guidance
    planned = guidance.get("requirement_worklist")
    if isinstance(planned, Mapping):
        items = planned.get("items")
        if isinstance(items, (list, tuple)):
            return [
                dict(item)
                for item in items[:24]
                if isinstance(item, Mapping)
            ]
    coverage = guidance.get("requirement_coverage")
    if isinstance(coverage, Mapping):
        gaps = coverage.get("gaps", ())
        if isinstance(gaps, (list, tuple)):
            for gap in gaps:
                if not isinstance(gap, Mapping):
                    continue
                requirement_id = str(gap.get("requirement_id", "")).strip()
                if requirement_id:
                    gaps_by_requirement[requirement_id] = gap

    requirements = sorted(
        (
            entity
            for entity in context.entities
            if entity.kind is EntityKind.REQUIREMENT
            and entity.meta.status
            not in {EntityStatus.REJECTED, EntityStatus.DEPRECATED}
        ),
        key=lambda entity: entity.id,
    )
    worklist: list[Mapping[str, object]] = []
    for requirement in requirements[:24]:
        gap = gaps_by_requirement.get(requirement.id, {})
        statement = requirement.payload.get("statement", requirement.meta.name)
        worklist.append({
            "requirement_id": requirement.id,
            "statement": str(statement).strip() or requirement.meta.name,
            "missing": list(gap.get("missing", ()))
            if isinstance(gap.get("missing", ()), (list, tuple))
            else [],
        })
    return worklist


def _compiler_repair_prompt(prompt: str, error: ContractViolation) -> str:
    return (
        f"{prompt.strip()}\n\n"
        "上一版 TaskProposal 的 JSON 结构正确，但无法编译为 ModelGraph Patch。"
        f"编译错误：{str(error)[:500]}\n"
        "请根据当前 context 和 compiler_feedback 只返回一个修正后的最小 TaskProposal JSON。"
        "每个 relation 的 source_ref 和 target_ref 必须是当前 context.entities 中存在的 canonical id，"
        "或是本次 entities 中定义且唯一的 local_ref；不得引用未定义的临时名称。"
        "保留可用事实，删除无法证明或无法连接的关系；不要返回解释、Patch、revision 或 DSL。"
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
