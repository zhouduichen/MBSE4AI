"""Adapter from TaskExecutionRequest to the existing GenerationRequest port."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from typing import Mapping

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.entities import EntityKind, EntityStatus
from rflp_lite.domain.errors import (
    ContractViolation,
    ProposalCompileFailure,
    StructuredOutputFailure,
)
from rflp_lite.domain.model import AddEntity, Deprecate, Patch, Relate, UpdateEntity
from rflp_lite.domain.relations import RelationPredicate, validate_endpoint_kinds
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
# Two requirements per provider call keeps a legitimate RFLP slice small while
# avoiding a five-call serial bottleneck for ordinary CASE-04-sized inputs.
# The aggregate patch is still validated after all batches are merged.
_VERTICAL_BATCH_SIZE = 2
# A two-requirement F/L/P/V&V slice still carries typed payloads, references,
# and trace relations.  Keep the batch boundary for context control, but let a
# legitimate slice use the configured provider budget instead of truncating
# its JSON envelope at the old 2048-token cap.
_VERTICAL_BATCH_OUTPUT_TOKEN_BUDGET = 4096


@dataclass(frozen=True, slots=True)
class _CompiledProposal:
    response: GenerationResponse
    proposal: TaskProposal
    patch: Patch | None
    compiler_repaired: bool = False
    batch_fallback: bool = False


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
                "entities": [
                    _model_entity(
                        item,
                        compact=request.task_id.startswith("vertical."),
                    )
                    for item in request.context_bundle.entities
                ],
                "relations": [
                    _model_relation(
                        item,
                        compact=request.task_id.startswith("vertical."),
                    )
                    for item in request.context_bundle.relations
                ],
            },
            "evidence": list(request.evidence_bundle),
            "controller_decisions": [
                dict(item) for item in request.context_bundle.controller_decisions
            ],
            "methodology_guidance": _model_methodology_guidance(request),
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
        batch_payloads = tuple(
            _scope_batch_payload(
                request,
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
                batch,
            )
            for index, batch in enumerate(batches, start=1)
        )
        compiled = self._complete_batches(request, contract, batch_payloads)
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
        if any(item.batch_fallback for item in compiled):
            diagnostics.append("batch_fallback=single_requirement")
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

    def _complete_batches(
        self,
        request: TaskExecutionRequest,
        contract: Mapping[str, object],
        payloads: tuple[Mapping[str, object], ...],
    ) -> tuple[_CompiledProposal, ...]:
        """Complete independent requirement batches without widening the write boundary."""

        if len(payloads) < 2:
            return tuple(
                self._complete_batch(request, contract, payload)
                for payload in payloads
            )

        def complete(payload: Mapping[str, object]):
            try:
                return self._complete_batch(request, contract, payload), None
            except Exception as exc:  # Preserve the original failure for routing.
                return None, exc

        if getattr(self.model, "supports_parallel_requirement_batching", False) is True:
            with ThreadPoolExecutor(
                max_workers=min(4, len(payloads)),
                thread_name_prefix="rflp-llm-batch",
            ) as executor:
                # executor.map preserves payload order, so merged hashes and
                # diagnostics remain deterministic even when responses finish
                # out of order at the provider.
                outcomes = tuple(executor.map(complete, payloads))
        else:
            sequential_outcomes = []
            for payload in payloads:
                outcome = complete(payload)
                failure = outcome[1]
                if failure is not None and not isinstance(
                    failure, (StructuredOutputFailure, ProposalCompileFailure)
                ):
                    raise failure
                sequential_outcomes.append(outcome)
            outcomes = tuple(sequential_outcomes)

        result: list[_CompiledProposal] = []
        for payload, (compiled, failure) in zip(payloads, outcomes):
            if compiled is not None:
                result.append(compiled)
                continue
            if failure is None:
                raise RuntimeError("batch completion returned no result")
            if not isinstance(failure, (StructuredOutputFailure, ProposalCompileFailure)):
                raise failure
            split_payloads = _split_requirement_batch(request, payload)
            if not split_payloads:
                raise failure
            result.extend(
                self._complete_batch(
                    request,
                    contract,
                    split_payload,
                    batch_fallback=True,
                )
                for split_payload in split_payloads
            )
        return tuple(result)

    def _complete_batch(
        self,
        request: TaskExecutionRequest,
        contract: Mapping[str, object],
        payload: Mapping[str, object],
        *,
        batch_fallback: bool = False,
    ) -> _CompiledProposal:
        token_budget = _batch_token_budget(request, payload)
        batch_instruction = _batch_instruction(
            request.task_id,
            payload.get("requirement_batch"),
        )
        response = self.model.complete_json(
            GenerationRequest(
                request.task_id,
                _structured_prompt(
                    request.prompt_text,
                    batch_instruction + _requirements_instruction(request, payload),
                ),
                payload,
                contract,
                token_budget,
            )
        )
        compiler_repaired = False
        proposal_payload = _sanitize_vertical_proposal(request, response.payload)
        try:
            proposal = parse_task_proposal(request, proposal_payload)
            patch = compile_task_proposal(request, proposal_payload)
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
                        token_budget,
                    )
                )
            repair_payload = _sanitize_vertical_proposal(request, repair_response.payload)
            try:
                proposal = parse_task_proposal(request, repair_payload)
                patch = compile_task_proposal(request, repair_payload)
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
        return _CompiledProposal(
            response,
            proposal,
            patch,
            compiler_repaired,
            batch_fallback,
        )


def _sanitize_vertical_proposal(
    request: TaskExecutionRequest,
    payload: Mapping[str, object],
) -> Mapping[str, object]:
    """Keep valid vertical output while removing transport-only copied metadata."""

    if not request.task_id.startswith("vertical."):
        return payload
    raw_relations = payload.get("relations")
    raw_entities = payload.get("entities")
    raw_updates = payload.get("updates")
    if not isinstance(raw_relations, (list, tuple)) or not isinstance(raw_entities, (list, tuple)):
        return payload
    context_kinds = {
        entity.id: entity.kind for entity in request.context_bundle.entities
    }
    local_kinds = {
        str(entity.get("local_ref")): EntityKind(str(entity.get("kind")))
        for entity in raw_entities
        if isinstance(entity, Mapping)
        and entity.get("local_ref")
        and entity.get("kind")
    }
    valid_relations = []
    for relation in raw_relations:
        if not isinstance(relation, Mapping):
            continue
        source_kind = _proposal_ref_kind(
            relation.get("source_ref"), local_kinds, context_kinds
        )
        target_kind = _proposal_ref_kind(
            relation.get("target_ref"), local_kinds, context_kinds
        )
        if source_kind is None or target_kind is None:
            valid_relations.append(relation)
            continue
        try:
            validate_endpoint_kinds(
                RelationPredicate(str(relation.get("predicate"))),
                source_kind,
                target_kind,
            )
        except (ContractViolation, ValueError):
            continue
        valid_relations.append(relation)
    result = dict(payload)
    if len(valid_relations) != len(raw_relations):
        result["relations"] = valid_relations
    inferred_relations = _infer_vertical_relations(
        request.task_id,
        raw_entities,
        valid_relations,
        local_kinds,
        context_kinds,
    )
    if len(inferred_relations) != len(valid_relations):
        result["relations"] = inferred_relations
    sanitized_updates = _sanitize_vertical_updates(request, raw_updates, context_kinds)
    if sanitized_updates is not None:
        result["updates"] = sanitized_updates
    return result


def _infer_vertical_relations(
    task_id: str,
    raw_entities: list[object] | tuple[object, ...],
    relations: list[Mapping[str, object]],
    local_kinds: Mapping[str, EntityKind],
    context_kinds: Mapping[str, EntityKind],
) -> list[Mapping[str, object]]:
    """Close typed links from payload IDs when a vertical response omits them.

    These links are derived only from canonical/local IDs already present in a
    validated typed payload.  The LLM still chooses the entities and payload;
    this adapter merely makes the ModelGraph's required edge representation
    explicit for downstream coverage and traceability.
    """

    if task_id not in {
        "vertical.functional",
        "vertical.logical",
        "vertical.physical",
        "vertical.verification_validation",
    }:
        return relations
    result = list(relations)
    existing = {
        (str(item.get("source_ref")), str(item.get("predicate")), str(item.get("target_ref")))
        for item in result
        if isinstance(item, Mapping)
    }

    def kind(reference: object) -> EntityKind | None:
        return _proposal_ref_kind(reference, local_kinds, context_kinds)

    def add(source_ref: object, predicate: RelationPredicate, target_ref: object) -> None:
        source = str(source_ref or "").strip()
        target = str(target_ref or "").strip()
        key = (source, predicate.value, target)
        if not source or not target or key in existing:
            return
        source_kind = kind(source)
        target_kind = kind(target)
        if source_kind is None or target_kind is None:
            return
        try:
            validate_endpoint_kinds(predicate, source_kind, target_kind)
        except ContractViolation:
            return
        result.append({
            "source_ref": source,
            "predicate": predicate.value,
            "target_ref": target,
            "evidence_ids": [],
        })
        existing.add(key)

    for raw_entity in raw_entities:
        if not isinstance(raw_entity, Mapping):
            continue
        local_ref = str(raw_entity.get("local_ref") or "").strip()
        entity_kind = kind(local_ref)
        payload = raw_entity.get("payload")
        if not local_ref or entity_kind is None or not isinstance(payload, Mapping):
            continue

        if task_id == "vertical.functional":
            if entity_kind is EntityKind.FUNCTIONAL_FLOW:
                endpoints = tuple(payload.get("source_function_ids", ())) + tuple(
                    payload.get("target_function_ids", ())
                )
                for function_ref in endpoints:
                    if kind(function_ref) is EntityKind.FUNCTION:
                        add(function_ref, RelationPredicate.EXCHANGES_WITH, local_ref)
            elif entity_kind is EntityKind.FUNCTIONAL_SCENARIO:
                for function_ref in payload.get("function_ids", ()):
                    if kind(function_ref) is EntityKind.FUNCTION:
                        add(function_ref, RelationPredicate.DERIVED_FROM, local_ref)
        elif task_id == "vertical.logical":
            if entity_kind is EntityKind.LOGICAL_COMPONENT:
                function_ref = payload.get("function_id")
                if kind(function_ref) is EntityKind.FUNCTION:
                    add(function_ref, RelationPredicate.ALLOCATED_TO, local_ref)
            elif entity_kind is EntityKind.INTERFACE:
                for logical_ref in payload.get("connected_component_ids", ()):
                    if kind(logical_ref) is EntityKind.LOGICAL_COMPONENT:
                        add(logical_ref, RelationPredicate.CONNECTED_TO, local_ref)
            elif entity_kind is EntityKind.STATE:
                logical_ref = payload.get("owner_id")
                if kind(logical_ref) is EntityKind.LOGICAL_COMPONENT:
                    add(logical_ref, RelationPredicate.DECOMPOSES, local_ref)
        elif task_id == "vertical.physical":
            logical_refs = []
            if payload.get("logical_id"):
                logical_refs.append(payload["logical_id"])
            logical_refs.extend(payload.get("source_logical_ids", ()))
            for logical_ref in logical_refs:
                if kind(logical_ref) is EntityKind.LOGICAL_COMPONENT:
                    add(logical_ref, RelationPredicate.ALLOCATED_TO, local_ref)
        elif task_id == "vertical.verification_validation":
            if entity_kind is EntityKind.VERIFICATION_CASE:
                for requirement_ref in payload.get("requirement_ids", ()):
                    if kind(requirement_ref) is EntityKind.REQUIREMENT:
                        add(requirement_ref, RelationPredicate.VERIFIED_BY, local_ref)
            elif entity_kind is EntityKind.VALIDATION_CASE:
                for requirement_ref in payload.get("requirement_ids", ()):
                    if kind(requirement_ref) is EntityKind.REQUIREMENT:
                        add(requirement_ref, RelationPredicate.VALIDATED_BY, local_ref)
            # Risk payloads are intentionally multi-requirement scopes.  The
            # assurance engine consumes their typed ``requirement_ids``
            # directly; fan-out into one derivedFrom relation per requirement
            # would duplicate the same risk across V&V batches and consume the
            # aggregate Patch operation budget without improving coverage.
    return result


def _sanitize_vertical_updates(
    request: TaskExecutionRequest,
    raw_updates: object,
    context_kinds: Mapping[str, EntityKind],
) -> list[Mapping[str, object]] | None:
    """Drop unknown fields copied into an existing entity payload update.

    Imported fixtures may carry bookkeeping such as ``fixture_id`` that is not
    part of the typed ModelGraph payload. The LLM still needs to update the
    typed fields (for example ``functional_behavior_ids``), so normalize only
    update payloads whose contract explicitly closes the property set.
    """

    if not isinstance(raw_updates, (list, tuple)):
        return None
    schemas = request.output_contract.get("x-payload-schemas", {})
    if not isinstance(schemas, Mapping):
        return None
    changed = False
    updates: list[Mapping[str, object]] = []
    for raw_update in raw_updates:
        if not isinstance(raw_update, Mapping):
            updates.append(raw_update)
            continue
        field_patch = raw_update.get("field_patch")
        entity_kind = context_kinds.get(str(raw_update.get("entity_id", "")))
        schema = schemas.get(entity_kind.value) if entity_kind is not None else None
        if not isinstance(field_patch, Mapping) or not isinstance(schema, Mapping):
            updates.append(raw_update)
            continue
        payload_patch = field_patch.get("payload")
        properties = schema.get("properties")
        if (
            not isinstance(payload_patch, Mapping)
            or schema.get("additionalProperties") is not False
            or not isinstance(properties, Mapping)
        ):
            updates.append(raw_update)
            continue
        filtered_payload = _valid_payload_patch(properties, payload_patch)
        if len(filtered_payload) == len(payload_patch):
            updates.append(raw_update)
            continue
        changed = True
        updates.append({
            **raw_update,
            "field_patch": {**field_patch, "payload": filtered_payload},
        })
    return updates if changed else None


def _valid_payload_patch(
    properties: Mapping[str, object],
    payload_patch: Mapping[str, object],
) -> Mapping[str, object]:
    """Retain only update fields that satisfy their individual field schema."""

    try:
        from jsonschema import ValidationError, validate
    except ImportError:
        return {
            key: value for key, value in payload_patch.items() if key in properties
        }
    result = {}
    for key, value in payload_patch.items():
        field_schema = properties.get(key)
        if not isinstance(field_schema, Mapping):
            continue
        try:
            validate(value, field_schema)
        except ValidationError:
            continue
        result[key] = value
    return result


def _proposal_ref_kind(
    reference: object,
    local_kinds: Mapping[str, EntityKind],
    context_kinds: Mapping[str, EntityKind],
) -> EntityKind | None:
    value = str(reference or "")
    return local_kinds.get(value) or context_kinds.get(value)


def _model_entity(entity, *, compact: bool = False) -> Mapping[str, object]:
    """Serialize only model-useful entity fields at the LLM wire boundary."""

    result = {
        "id": entity.id,
        "kind": entity.kind.value,
        "name": entity.meta.name,
        "payload": _model_entity_payload(entity, compact=compact),
    }
    if not compact:
        result.update({
            "status": entity.meta.status.value,
            "producer": entity.meta.producer.value,
            "confidence": entity.meta.confidence,
            "source_ids": list(entity.meta.source_ids),
            "evidence_ids": list(entity.meta.evidence_ids),
            "lifecycle_ids": list(entity.meta.lifecycle_ids),
        })
    return result


def _model_entity_payload(entity, *, compact: bool) -> Mapping[str, object]:
    payload = dict(entity.payload)
    if compact and entity.kind is EntityKind.REQUIREMENT:
        payload.pop("fixture_id", None)
    return payload


def _model_relation(relation, *, compact: bool = False) -> Mapping[str, object]:
    result = {
        "source_id": relation.source_id,
        "predicate": relation.predicate.value,
        "target_id": relation.target_id,
    }
    if not compact:
        result.update({
            "id": relation.id,
            "evidence_ids": list(relation.evidence_ids),
        })
    return result


def _model_methodology_guidance(
    request: TaskExecutionRequest,
) -> Mapping[str, object]:
    """Avoid sending duplicate methodology report projections to the model."""

    guidance = dict(request.context_bundle.methodology_guidance)
    if not request.task_id.startswith("vertical."):
        return guidance
    retained = {
        "architecture_synthesis",
        "version",
        "task_id",
        "stage",
        "metrics",
        "recommended_tasks",
        "requirement_coverage",
        "context_selection",
        "impacted_entity_ids",
        "decision_package",
        "stage_contract",
        "stage_completion",
    }
    result = {key: guidance[key] for key in retained if key in guidance}
    if isinstance(result.get("requirement_coverage"), Mapping):
        result["requirement_coverage"] = _compact_coverage(
            result["requirement_coverage"]
        )
    if isinstance(result.get("context_selection"), Mapping):
        result["context_selection"] = _compact_context_selection(
            result["context_selection"]
        )
    if isinstance(result.get("stage_completion"), Mapping):
        result["stage_completion"] = _compact_stage_completion(
            result["stage_completion"]
        )
    if isinstance(result.get("decision_package"), Mapping):
        result["decision_package"] = _compact_decision_package(
            result["decision_package"]
        )
    return result


def _compact_coverage(value: Mapping[str, object]) -> Mapping[str, object]:
    """Keep requirement coverage gaps while removing duplicate trace paths."""

    result = {
        key: value[key]
        for key in ("id", "stage", "passed", "requirement_count", "covered_count")
        if key in value
    }
    missing = value.get("missing_requirement_ids")
    if isinstance(missing, (list, tuple)):
        result["missing_requirement_ids"] = list(missing)
    gaps = value.get("gaps")
    if isinstance(gaps, (list, tuple)):
        result["gaps"] = [
            {
                key: gap[key]
                for key in ("requirement_id", "missing")
                if key in gap
            }
            for gap in gaps
            if isinstance(gap, Mapping)
        ]
    return result


def _compact_context_selection(value: Mapping[str, object]) -> Mapping[str, object]:
    """Expose selection provenance as IDs, not as a second graph projection."""

    result = {
        key: value[key]
        for key in (
            "policy",
            "available_budget",
            "token_estimate",
            "selected_entity_ids",
            "omitted_entity_ids",
            "selected_requirement_ids",
            "omitted_requirement_ids",
        )
        if key in value
    }
    return result


def _compact_stage_completion(value: Mapping[str, object]) -> Mapping[str, object]:
    """Preserve completion signals without resending all coverage paths."""

    result = {
        "issue_codes": list(value.get("issue_codes", ()))
        if isinstance(value.get("issue_codes"), (list, tuple))
        else [],
    }
    checks = value.get("checks")
    if not isinstance(checks, (list, tuple)):
        return result
    compact_checks = []
    for check in checks:
        if not isinstance(check, Mapping):
            continue
        compact = {
            key: check[key]
            for key in ("id", "passed", "requirement_count", "covered_count")
            if key in check
        }
        missing = check.get("missing_requirement_ids")
        if isinstance(missing, (list, tuple)):
            compact["missing_requirement_ids"] = list(missing)
        gaps = check.get("gaps")
        if isinstance(gaps, (list, tuple)):
            compact["gaps"] = [
                {
                    key: gap[key]
                    for key in ("requirement_id", "missing")
                    if key in gap
                }
                for gap in gaps
                if isinstance(gap, Mapping)
            ]
        compact_checks.append(compact)
    result["checks"] = compact_checks
    return result


def _compact_decision_package(value: Mapping[str, object]) -> Mapping[str, object]:
    """Keep only the current-stage decision evidence needed by the LLM."""

    result = {
        key: value[key]
        for key in ("stage", "decision_count", "truncated")
        if key in value
    }
    records = value.get("decision_records")
    if isinstance(records, (list, tuple)):
        result["decision_records"] = [
            {
                key: record[key]
                for key in ("step", "decision", "basis")
                if key in record
            }
            for record in records
            if isinstance(record, Mapping)
        ]
    return result


def _requirements_instruction(
    request: TaskExecutionRequest,
    payload: Mapping[str, object],
) -> str:
    """Tell an incremental R call which missing kinds must be closed."""

    if request.task_id != "vertical.requirements":
        return ""
    context = payload.get("context")
    if not isinstance(context, Mapping):
        return ""
    entities = context.get("entities")
    present = {
        str(entity.get("kind", ""))
        for entity in entities
        if isinstance(entity, Mapping)
    } if isinstance(entities, (list, tuple)) else set()
    required = (
        "system", "stakeholder", "concern", "lifecycle_stage",
        "lifecycle_transition", "scenario_hypothesis", "use_case",
        "operational_scenario", "activity", "requirement",
    )
    missing = tuple(kind for kind in required if kind not in present)
    if not missing:
        return "已有 R 层类型都已存在；只用最小 updates/relations 修复语义，不要新增实体。"
    return (
        "这是增量闭合。当前 Proposal 必须为每个缺失类型各生成至少一个且至多一个实体，"
        "并优先覆盖以下缺失类型：" + ", ".join(missing) + "。"
        "已有类型禁止新增；不要用多个 concern 或 use_case 消耗实体名额。"
        "R关系只允许四种端点模板：hasConcern=stakeholder/system→concern，"
        "participatesIn=stakeholder→operational_scenario，"
        "occursIn=activity/operational_scenario→lifecycle_stage，"
        "derivedFrom=operational_scenario→use_case 或 requirement→concern/activity；"
        "stakeholder→use_case 不能使用 participatesIn；"
        "Requirement 的 level 只能是 stakeholder/system/functional/technical，type 只能是 "
        "functional/performance/interface/safety/constraint；"
        "不要使用 decomposes，也不要反转 source_ref 和 target_ref。"
    )

_STRUCTURED_RULES = (
    "仅返回 TaskProposal JSON 对象，必须包含 entities、relations、updates、deprecations、reason；"
    "除非任务明确要求修改或弃用既有实体，否则 updates 和 deprecations 必须为空数组；"
    "每个 entities[i].local_ref 必须在当前 Proposal 内唯一；local_ref 只是本轮临时引用，不是领域 ID；"
    "relations 只能引用当前上下文中的 canonical entity id 或本 Proposal 内唯一的 local_ref；"
    "读取 methodology_guidance 中的确定性检查结果，优先补齐其指出的当前阶段缺口；不要把 guidance 当作新的实体事实；"
    "如果 methodology_guidance.decision_package 存在，只按当前 stage 的 decision_records 推理；其它阶段记录不能替代当前阶段工作；"
    "Requirements 阶段若 requirement_quality_coverage 或 requirement_verification_method_coverage 低于 1，逐条补充可复核字段或将不确定性写入 open_questions，不得默认为已满足；"
    "如果 methodology_guidance.stage_contract 存在，必须按其中的 reasoning_tasks 完成当前阶段，并遵守 required_kinds 与 allowed_predicates；"
    "如果 stage_completion.requirement_coverage.passed 为 false，必须优先修复其中列出的 missing_requirement_ids 和 coverage gap；"
    "如果 requirement_worklist 非空，必须逐条覆盖其中每个 requirement_id；不得把多条 Requirement 合并成一个无法追溯的下游对象；"
    "requirement_worklist.current 是已有的 canonical 追溯对象；优先复用其中的 ID，只修复 missing 列出的当前阶段缺口；"
    "如果 worklist item 含 available_current 和 unavailable_current，只能引用 available_current 中且确实存在于 context.entities 的 ID；"
    "unavailable_current 仅表示完整图中的延后追溯，不能引用、更新或声称本轮已经修复；无法在当前上下文完成的部分写入 open_questions；"
    "如果 requirement_worklist.truncated 为 true，只处理 items 中明确提供且在 context 中可见的 Requirement，不得声称已覆盖 omitted_requirement_ids；"
    "R层关系方向必须严格：hasConcern 为 stakeholder/system→concern，participatesIn 为 stakeholder→operational_scenario，"
    "occursIn 为 activity/operational_scenario→lifecycle_stage，derivedFrom 可为 operational_scenario→use_case 或 requirement→concern/activity；不要反转 source_ref 和 target_ref；"
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


def _scope_batch_payload(
    request: TaskExecutionRequest,
    payload: Mapping[str, object],
    batch: tuple[Mapping[str, object], ...] | list[Mapping[str, object]],
) -> Mapping[str, object]:
    """Keep a multi-request wire payload grounded in its current batch."""

    result = dict(payload)
    if "requirement_worklist" not in result:
        return result
    result["requirement_worklist"] = list(batch)
    if not isinstance(result.get("requirement_batch"), Mapping):
        return result
    context = result.get("context")
    if not isinstance(context, Mapping):
        return result
    requirement_ids = {
        str(item.get("requirement_id", ""))
        for item in batch
        if isinstance(item, Mapping) and str(item.get("requirement_id", ""))
    }
    if not requirement_ids:
        return result
    entities = context.get("entities")
    if not isinstance(entities, (list, tuple)):
        return result
    scoped_entities = [
        entity
        for entity in entities
        if not isinstance(entity, Mapping)
        or entity.get("kind") != EntityKind.REQUIREMENT.value
        or str(entity.get("id", "")) in requirement_ids
    ]
    visible_ids = {
        str(entity.get("id", ""))
        for entity in scoped_entities
        if isinstance(entity, Mapping) and str(entity.get("id", ""))
    }
    relations = context.get("relations")
    scoped_relations = relations
    if isinstance(relations, (list, tuple)):
        scoped_relations = [
            relation
            for relation in relations
            if isinstance(relation, Mapping)
            and str(relation.get("source_id", "")) in visible_ids
            and str(relation.get("target_id", "")) in visible_ids
        ]
    scoped_context = {
        **context,
        "entities": scoped_entities,
        "relations": scoped_relations,
    }
    result["context"] = scoped_context
    result["context_hash"] = canonical_hash(scoped_context)
    return result


def _split_requirement_batch(
    request: TaskExecutionRequest,
    payload: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    """Turn one failed multi-requirement request into bounded singleton calls."""

    worklist = payload.get("requirement_worklist")
    if not isinstance(worklist, (list, tuple)) or len(worklist) < 2:
        return ()
    metadata = payload.get("requirement_batch")
    result: list[Mapping[str, object]] = []
    for offset, item in enumerate(worklist):
        if not isinstance(item, Mapping):
            continue
        split_payload = dict(payload)
        split_payload["requirement_worklist"] = [item]
        if isinstance(metadata, Mapping):
            split_metadata = dict(metadata)
            split_metadata["is_first"] = bool(metadata.get("is_first")) and offset == 0
            split_payload["requirement_batch"] = split_metadata
        result.append(_scope_batch_payload(request, split_payload, [item]))
    return tuple(result)


def _batch_token_budget(
    request: TaskExecutionRequest,
    payload: Mapping[str, object],
) -> int:
    """Keep multi-requirement provider calls bounded without shrinking R output."""

    batch = payload.get("requirement_batch")
    if request.task_id not in _VERTICAL_BATCH_TASKS or not isinstance(batch, Mapping):
        return request.token_budget
    return min(request.token_budget, _VERTICAL_BATCH_OUTPUT_TOKEN_BUDGET)


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
                for item in items
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
    for requirement in requirements:
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
        "更新既有实体时，field_patch.payload 只能包含该实体类型 schema 中允许的字段；"
        "不要复制 context 中的 fixture_id 或其它导入元数据。"
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
