"""Adapter from TaskExecutionRequest to the existing GenerationRequest port."""

from __future__ import annotations

import json
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from typing import Mapping

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.entities import EntityKind, EntityStatus
from rflp_lite.domain.errors import (
    ContractViolation,
    ProposalCompileFailure,
    StructuredOutputFailure,
    TransportFailure,
)
from rflp_lite.domain.model import (
    AddEntity,
    Deprecate,
    ModelGraph,
    Patch,
    Relate,
    UpdateEntity,
    apply_patch,
)
from rflp_lite.domain.relations import RelationPredicate, validate_endpoint_kinds
from rflp_lite.methodology.contracts import StepStatus, TaskExecutionRequest, TaskExecutionResponse
from rflp_lite.methodology.proposal_compiler import (
    _GRAPH_REFERENCE_FIELDS,
    TaskProposal,
    compile_task_proposal,
    parse_task_proposal,
)
from rflp_lite.methodology.policy import PatchPolicy
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
_R_STAGE_KINDS = (
    "system",
    "stakeholder",
    "concern",
    "lifecycle_stage",
    "lifecycle_transition",
    "scenario_hypothesis",
    "use_case",
    "operational_scenario",
    "activity",
    "requirement",
)
_R_BACKBONE_GROUPS = (
    (
        "r_backbone_operational",
        (
            "system",
            "stakeholder",
            "concern",
            "lifecycle_stage",
            "lifecycle_transition",
        ),
    ),
    (
        "r_backbone_behavior",
        (
            "scenario_hypothesis",
            "use_case",
            "operational_scenario",
            "activity",
        ),
    ),
)
_VERTICAL_BATCH_THRESHOLD = 3
# Two requirements per provider call keeps a legitimate RFLP slice small while
# avoiding a five-call serial bottleneck for ordinary CASE-04-sized inputs.
# The aggregate patch is still validated after all batches are merged.
_VERTICAL_BATCH_SIZE = 2
# A two-requirement F/L/P/V&V slice still carries typed payloads, references,
# and trace relations.  Keep the batch boundary for context control, but let a
# legitimate slice use a bounded provider budget instead of truncating its
# JSON envelope at the old 2048-token cap. Singleton recovery is smaller
# because it has only one requirement to cover.
_VERTICAL_BATCH_OUTPUT_TOKEN_BUDGET = 3072
_VERTICAL_SINGLETON_OUTPUT_TOKEN_BUDGET = 2048
_VERTICAL_CURRENT_FIELDS = (
    "function_ids",
    "logical_component_ids",
    "physical_ids",
    "verification_case_ids",
    "validation_case_ids",
)
_MISSING_VERTICAL_VALUE = object()


@dataclass(frozen=True, slots=True)
class _CompiledProposal:
    response: GenerationResponse
    proposal: TaskProposal
    patch: Patch | None
    compiler_repaired: bool = False
    batch_fallback: bool = False
    slice_kind: str = ""
    slice_index: int = 0
    slice_count: int = 0


class StructuredModelRuntime:
    def __init__(self, model: GenerativeModel):
        self.model = model
        self.vertical_batch_size = max(
            1,
            min(32, int(getattr(model, "vertical_batch_size", _VERTICAL_BATCH_SIZE))),
        )
        self.vertical_batch_output_token_budget = max(
            256,
            int(
                getattr(
                    model,
                    "vertical_batch_output_token_budget",
                    _VERTICAL_BATCH_OUTPUT_TOKEN_BUDGET,
                )
            ),
        )
        try:
            self.vertical_vv_batch_size = max(
                1,
                min(
                    32,
                    int(
                        getattr(
                            model,
                            "vertical_vv_batch_size",
                            self.vertical_batch_size,
                        )
                    ),
                ),
            )
        except (TypeError, ValueError):
            self.vertical_vv_batch_size = self.vertical_batch_size
        self.vertical_singleton_output_token_budget = max(
            256,
            int(
                getattr(
                    model,
                    "vertical_singleton_output_token_budget",
                    _VERTICAL_SINGLETON_OUTPUT_TOKEN_BUDGET,
                )
            ),
        )
        try:
            self.max_parallel_requests = max(
                1,
                min(4, int(getattr(model, "max_parallel_requests", 4))),
            )
        except (TypeError, ValueError):
            self.max_parallel_requests = 4

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
        if request.task_id == "vertical.requirements":
            compiled = self._execute_r_stage(request, payload, contract)
        else:
            batches = _requirement_batches(
                request,
                payload.get("requirement_worklist", []),
                self.model,
                batch_size=(
                    self.vertical_vv_batch_size
                    if request.task_id == _VV_BATCH_TASK
                    else self.vertical_batch_size
                ),
            )
            batch_descriptors = _batch_descriptors(request, batches, self.model)
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
                                    "count": len(batch_descriptors),
                                    "is_first": index == 1,
                                    "requirement_ids": [
                                        str(item.get("requirement_id", ""))
                                        for item in batch
                                        if isinstance(item, Mapping)
                                        and str(item.get("requirement_id", ""))
                                    ],
                                    **(
                                        {"case_kind": case_kind}
                                        if case_kind
                                        else {}
                                    ),
                                }
                            }
                            if len(batch_descriptors) > 1
                            else {}
                        ),
                    },
                    batch,
                )
                for index, (batch, case_kind) in enumerate(batch_descriptors, start=1)
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
        if request.task_id == "vertical.requirements":
            diagnostics.extend(
                "r_slice=" + (item.slice_kind or "legacy")
                + f"[{item.slice_index}/{item.slice_count}]"
                for item in compiled
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

    def _execute_r_stage(
        self,
        request: TaskExecutionRequest,
        payload: Mapping[str, object],
        contract: Mapping[str, object],
    ) -> tuple[_CompiledProposal, ...]:
        """Complete R backbone slices before independent Requirement closures."""

        slices = _r_stage_slices(
            request,
            payload,
            single_kind=bool(getattr(self.model, "r_backbone_single_kind", False)),
        )
        if not any(isinstance(item.get("r_slice"), Mapping) for item in slices):
            return self._complete_batches(request, contract, slices)
        working_graph = ModelGraph(
            request.context_bundle.project_id,
            request.context_bundle.entities,
            request.context_bundle.relations,
            request.context_bundle.revision,
        )
        compiled: list[_CompiledProposal] = []
        backbone = [
            item for item in slices
            if item["r_slice"]["slice_kind"] != "r_requirement"
        ]
        closures = [
            item for item in slices
            if item["r_slice"]["slice_kind"] == "r_requirement"
        ]
        for slice_payload in backbone:
            current_request = _request_for_working_graph(request, working_graph)
            current_payload = _r_payload_for_request(current_request, slice_payload)
            try:
                item = self._complete_batch(
                    current_request,
                    contract,
                    current_payload,
                )
            except (StructuredOutputFailure, ProposalCompileFailure) as exc:
                metadata = current_payload.get("r_slice")
                allowed_kinds = (
                    tuple(str(item) for item in metadata.get("allowed_kinds", ()))
                    if isinstance(metadata, Mapping)
                    else ()
                )
                if len(allowed_kinds) > 1:
                    for offset, kind in enumerate(allowed_kinds):
                        narrowed_payload = _r_payload_for_request(
                            _request_for_working_graph(request, working_graph),
                            _narrow_r_backbone_payload(
                                current_payload,
                                kind,
                                offset,
                                len(allowed_kinds),
                            ),
                        )
                        try:
                            narrowed_item = self._complete_batch(
                                current_request,
                                contract,
                                narrowed_payload,
                            )
                        except (
                            StructuredOutputFailure,
                            ProposalCompileFailure,
                            TransportFailure,
                        ) as narrowed_error:
                            raise _annotate_r_slice_failure(
                                narrowed_error,
                                narrowed_payload,
                            ) from narrowed_error
                        compiled.append(narrowed_item)
                        if narrowed_item.patch is not None:
                            working_graph = apply_patch(
                                working_graph,
                                _rebase_patch(
                                    narrowed_item.patch,
                                    working_graph.revision,
                                ),
                            )
                    continue
                raise _annotate_r_slice_failure(exc, current_payload) from exc
            except TransportFailure as exc:
                raise _annotate_r_slice_failure(exc, current_payload) from exc
            compiled.append(item)
            if item.patch is not None:
                working_graph = apply_patch(
                    working_graph,
                    _rebase_patch(item.patch, working_graph.revision),
                )
        if closures:
            current_request = _request_for_working_graph(request, working_graph)
            closure_payloads = tuple(
                _r_payload_for_request(current_request, item)
                for item in closures
            )
            try:
                compiled.extend(
                    self._complete_batches(current_request, contract, closure_payloads)
                )
            except (StructuredOutputFailure, ProposalCompileFailure, TransportFailure) as exc:
                failed_payload = next(
                    (
                        item for item in closure_payloads
                        if isinstance(item.get("r_slice"), Mapping)
                    ),
                    closure_payloads[0] if closure_payloads else {},
                )
                raise _annotate_r_slice_failure(exc, failed_payload) from exc
        return tuple(compiled)

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
                max_workers=min(self.max_parallel_requests, len(payloads)),
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
        effective_request = request
        case_kind = _vv_case_kind(payload)
        full_contract = request.output_contract
        if case_kind:
            full_contract = _vv_case_contract(full_contract, case_kind)
        if request.task_id == "vertical.requirements" and isinstance(
            payload.get("r_slice"), Mapping
        ):
            full_contract = _r_slice_contract(full_contract, payload)
        if case_kind or isinstance(payload.get("r_slice"), Mapping):
            effective_contract = _output_schema(full_contract)
            effective_request = replace(
                request,
                output_contract=full_contract,
                patch_policy=(
                    _r_slice_patch_policy(request, payload)
                    if isinstance(payload.get("r_slice"), Mapping)
                    else request.patch_policy
                ),
            )
        else:
            effective_contract = contract
        token_budget = _batch_token_budget(
            request,
            payload,
            singleton_fallback=batch_fallback,
            batch_output_token_budget=self.vertical_batch_output_token_budget,
            singleton_output_token_budget=self.vertical_singleton_output_token_budget,
        )
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
                effective_contract,
                token_budget,
            )
        )
        compiler_repaired = False
        proposal_payload = _sanitize_vertical_proposal(effective_request, response.payload)
        try:
            proposal = parse_task_proposal(effective_request, proposal_payload)
            patch = compile_task_proposal(effective_request, proposal_payload)
        except ContractViolation as first_error:
            if _is_wide_requirement_batch(payload):
                raise ProposalCompileFailure(
                    str(first_error),
                    raw_response=json.dumps(
                        response.payload,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    initial_raw_response=json.dumps(
                        response.payload,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    schema_hash=canonical_hash(effective_contract),
                    provider_id=response.provider_id,
                    model_id=response.model_id,
                    finish_reason=response.finish_reason,
                    usage=response.usage,
                ) from first_error
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
                        effective_contract,
                        token_budget,
                    )
                )
            repair_payload = _sanitize_vertical_proposal(
                effective_request,
                repair_response.payload,
            )
            try:
                proposal = parse_task_proposal(effective_request, repair_payload)
                patch = compile_task_proposal(effective_request, repair_payload)
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
                    schema_hash=canonical_hash(effective_contract),
                    retry_count=1,
                    provider_id=repair_response.provider_id or response.provider_id,
                    model_id=repair_response.model_id or response.model_id,
                    finish_reason=repair_response.finish_reason,
                    usage=repair_response.usage,
                ) from second_error
            response = replace(repair_response, repaired=True)
            compiler_repaired = True
        slice_metadata = payload.get("r_slice")
        if not isinstance(slice_metadata, Mapping):
            slice_metadata = {}
        return _CompiledProposal(
            response,
            proposal,
            patch,
            compiler_repaired,
            batch_fallback,
            str(slice_metadata.get("slice_kind", "")),
            int(slice_metadata.get("slice_index", 0) or 0),
            int(slice_metadata.get("slice_count", 0) or 0),
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
    filtered_entities = []
    discarded_local_refs: set[str] = set()
    for entity in raw_entities:
        if not isinstance(entity, Mapping):
            filtered_entities.append(entity)
            continue
        kind = str(entity.get("kind", ""))
        payload_value = entity.get("payload")
        if (
            request.task_id == "vertical.verification_validation"
            and kind in {EntityKind.HAZARD.value, EntityKind.FAILURE_MODE.value}
            and isinstance(payload_value, Mapping)
            and not payload_value
        ):
            local_ref = str(entity.get("local_ref", "")).strip()
            if local_ref:
                discarded_local_refs.add(local_ref)
            continue
        filtered_entities.append(entity)
    raw_entities = filtered_entities
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
            # A useful entity batch must not be discarded because the model
            # guessed a display name or an unavailable downstream id.  The
            # relation cannot be materialized safely, so leave it out and let
            # typed payload references/coverage determine what remains open.
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
    if discarded_local_refs:
        result["entities"] = list(raw_entities)
    sanitized_payloads = _sanitize_vertical_entity_payloads(request, raw_entities)
    if sanitized_payloads is not None:
        result["entities"] = sanitized_payloads
        raw_entities = sanitized_payloads
    if len(valid_relations) != len(raw_relations):
        result["relations"] = valid_relations
    sanitized_entities = _sanitize_vertical_entity_references(
        request,
        raw_entities,
        context_kinds,
        set(local_kinds),
    )
    if sanitized_entities is not None:
        result["entities"] = sanitized_entities
        raw_entities = sanitized_entities
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


def _sanitize_vertical_entity_payloads(
    request: TaskExecutionRequest,
    raw_entities: list[object] | tuple[object, ...],
) -> list[object] | None:
    """Remove only closed-schema fields that are not part of ModelGraph.

    The provider adapter performs the same normalization before JSON-schema
    validation.  Keep this second, context-aware guard at the compiler
    boundary because some OpenAI-compatible endpoints return a weakened
    transport schema and because benchmark fixtures intentionally contain
    import-only metadata.  Values are not coerced or invented here; semantic
    validation remains authoritative after the harmless metadata is removed.
    """

    schemas = request.output_contract.get("x-payload-schemas", {})
    if not isinstance(schemas, Mapping):
        return None
    changed = False
    entities: list[object] = []
    for raw_entity in raw_entities:
        if not isinstance(raw_entity, Mapping):
            entities.append(raw_entity)
            continue
        kind = str(raw_entity.get("kind", "")).strip()
        schema = schemas.get(kind)
        payload = raw_entity.get("payload")
        properties = schema.get("properties") if isinstance(schema, Mapping) else None
        if (
            not isinstance(payload, Mapping)
            or not isinstance(schema, Mapping)
            or schema.get("additionalProperties") is not False
            or not isinstance(properties, Mapping)
        ):
            entities.append(raw_entity)
            continue
        filtered = {
            str(key): value
            for key, value in payload.items()
            if key in properties
        }
        if len(filtered) == len(payload):
            entities.append(raw_entity)
            continue
        changed = True
        entities.append({**raw_entity, "payload": filtered})
    return entities if changed else None


def _sanitize_vertical_entity_references(
    request: TaskExecutionRequest,
    raw_entities: list[object] | tuple[object, ...],
    context_kinds: Mapping[str, EntityKind],
    local_refs: set[str],
) -> list[object] | None:
    """Drop unresolvable typed IDs before the proposal compiler rejects a batch.

    Models sometimes turn a free-form flow description into an ID-looking
    value (for example ``flow-...-1``) even though that entity was not
    declared in the current Proposal or context. Graph-reference fields are
    the only fields affected; prose and engineering evidence remain intact.
    Removing an unresolvable edge leaves the typed object available for
    compiler validation and makes the missing link visible to downstream
    coverage instead of discarding the entire parallel batch.
    """

    if not request.task_id.startswith("vertical."):
        return None
    known_ids = set(context_kinds) | set(local_refs)
    changed = False

    def clean(value: object, field: str = "") -> object:
        nonlocal changed
        if field in _GRAPH_REFERENCE_FIELDS:
            if isinstance(value, (list, tuple)):
                filtered = [
                    item for item in value
                    if not isinstance(item, str) or item.strip() in known_ids
                ]
                if len(filtered) != len(value):
                    changed = True
                return list(dict.fromkeys(filtered))
            if isinstance(value, str) and value.strip() not in known_ids:
                changed = True
                return _MISSING_VERTICAL_VALUE
            return value
        if isinstance(value, Mapping):
            result = {}
            for key, item in value.items():
                cleaned = clean(item, str(key))
                if cleaned is _MISSING_VERTICAL_VALUE:
                    continue
                result[key] = cleaned
            return result
        if isinstance(value, list):
            return [clean(item, field) for item in value]
        return value

    sanitized: list[object] = []
    for raw_entity in raw_entities:
        if not isinstance(raw_entity, Mapping):
            sanitized.append(raw_entity)
            continue
        payload = raw_entity.get("payload")
        if not isinstance(payload, Mapping):
            sanitized.append(raw_entity)
            continue
        cleaned_payload = clean(payload)
        if cleaned_payload is payload:
            sanitized.append(raw_entity)
            continue
        sanitized.append({**raw_entity, "payload": cleaned_payload})
    return sanitized if changed else None


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
                if kind(logical_ref) is not EntityKind.LOGICAL_COMPONENT:
                    logical_refs = [
                        ref
                        for ref, ref_kind in (*local_kinds.items(), *context_kinds.items())
                        if ref_kind is EntityKind.LOGICAL_COMPONENT
                    ]
                    if len(set(logical_refs)) == 1:
                        logical_ref = logical_refs[0]
                        if isinstance(payload, dict):
                            payload["owner_id"] = logical_ref
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
    if task_id == "vertical.logical":
        for relation in list(result):
            if relation.get("predicate") != RelationPredicate.EXCHANGES_WITH.value:
                continue
            source_ref = relation.get("source_ref")
            target_ref = relation.get("target_ref")
            if (
                kind(source_ref) is EntityKind.LOGICAL_COMPONENT
                and kind(target_ref) is EntityKind.INTERFACE
            ):
                add(source_ref, RelationPredicate.CONNECTED_TO, target_ref)
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
        entity_id = str(raw_update.get("entity_id", ""))
        if entity_id not in context_kinds:
            # A vertical batch may contain a new V&V entity whose canonical ID
            # is not known until compilation.  An update cannot target that
            # entity, and an unknown target is outside the task write scope;
            # drop only this operation so the rest of the batch can commit.
            changed = True
            continue
        field_patch = raw_update.get("field_patch")
        entity_kind = context_kinds.get(entity_id)
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
    slice_metadata = payload.get("r_slice")
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
    guidance = payload.get("methodology_guidance")
    failed_checks: list[str] = []
    if isinstance(guidance, Mapping):
        completion = guidance.get("stage_completion")
        checks = completion.get("checks") if isinstance(completion, Mapping) else None
        if isinstance(checks, (list, tuple)):
            failed_checks = [
                str(check.get("id", ""))
                for check in checks
                if isinstance(check, Mapping) and check.get("passed") is False
            ]
    check_hint = (
        "方法论检查未通过：" + ", ".join(item for item in failed_checks if item) +
        "。本轮必须优先修复这些检查指出的缺口。"
        if failed_checks else ""
    )
    if isinstance(slice_metadata, Mapping):
        slice_kind = str(slice_metadata.get("slice_kind", ""))
        allowed_kinds = tuple(
            str(kind) for kind in slice_metadata.get("allowed_kinds", ())
        )
        if slice_kind == "r_requirement":
            requirement_ids = tuple(
                str(item) for item in slice_metadata.get("requirement_ids", ())
            )
            return (
                "当前是 R Requirement closure slice；只处理指定 canonical Requirement："
                + ", ".join(requirement_ids)
                + "。entities 必须为空；只允许对该 Requirement 使用 updates，或补充"
                " Requirement→Concern/UseCase/Activity 的 derivedFrom、UseCase→Activity 的"
                " decomposes 关系。不得新增任何实体、更新其它 Requirement、反转关系方向，"
                "也不得声称已覆盖不在当前上下文中的对象。"
                + check_hint
            )
        return (
            "当前是 R backbone slice；本轮只允许生成以下类型："
            + ", ".join(allowed_kinds)
            + "。不要生成 Requirement，也不要重复已有类型；先形成可复用的 canonical"
            " operational/behavior backbone，再由后续 Requirement closure 建立追溯。"
            "关系只能使用当前契约允许的 hasConcern、participatesIn、occursIn、derivedFrom、"
            "decomposes，并保持 source_ref→target_ref 方向正确。"
            + check_hint
        )
    if not missing:
        return (
            "已有 R 层类型都已存在；只用最小 updates/relations 修复语义，不要新增实体。"
            + check_hint
        )
    single_kind_hint = (
        f"当前唯一缺失类型是 {missing[0]}；本轮至少生成一个且最多生成一个该类型实体，"
        "不要生成其它新类型。"
        if len(missing) == 1 else ""
    )
    activity_hint = (
        "Activity 是当前唯一的闭合缺口；必须从已有 Requirement 和 Operational Scenario"
        "抽取一个最小可执行行为，直接生成 kind=activity 实体。payload 至少包含 steps 和"
        "branches，并在 branches 中明确 normal、failure、alternative、boundary、exception"
        "五类分支；即使细节不完整也使用当前上下文可证实的短句，不要把 Activity 缺口改写成"
        "open_questions 或声称信息不足。"
        if missing == ("activity",) else ""
    )
    return (
        "这是增量闭合。当前 Proposal 必须为每个缺失类型各生成至少一个且至多一个实体，"
        "并优先覆盖以下缺失类型：" + ", ".join(missing) + "。"
        + single_kind_hint
        + activity_hint
        + check_hint
        + "已有类型禁止新增；不要用多个 concern 或 use_case 消耗实体名额。"
        "R关系只允许四种端点模板：hasConcern=stakeholder/system→concern，"
        "participatesIn=stakeholder→operational_scenario，"
        "occursIn=activity/operational_scenario→lifecycle_stage，"
        "derivedFrom=operational_scenario→use_case 或 requirement→concern/use_case/activity；"
        "decomposes=use_case→activity；"
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
        "occursIn 为 activity/operational_scenario→lifecycle_stage，derivedFrom 可为 operational_scenario→use_case 或 requirement→concern/use_case/activity，decomposes 为 use_case→activity；不要反转 source_ref 和 target_ref；"
    "复用已有 Requirement、Function、LogicalComponent、PhysicalBlock 和 V&V Case 的 canonical id，只补缺失的 typed 实体或关系；"
    "无法由当前上下文证明的缺口写入 open_questions，不得把不完整覆盖声称为完成；"
    "不要返回 operations、Patch ID、revision、status、producer 或 kind/value/path 更新 DSL；不要解释。"
)


def _structured_prompt(prompt: str, batch_instruction: str = "") -> str:
    return f"{str(prompt).strip()}\n\n{_STRUCTURED_RULES}{batch_instruction}"


def _batch_instruction(task_id: str, meta: object) -> str:
    if not isinstance(meta, Mapping):
        return _logical_stage_instruction(task_id)
    index = meta.get("index")
    count = meta.get("count")
    if task_id != _VV_BATCH_TASK:
        return (
            f"当前是 {task_id} 第 {index}/{count} 个需求批次。"
            "只处理 requirement_worklist 中的 canonical Requirement；"
            "不得为其它批次需求新增实体或更新，也不要把本批缺口合并成无法追溯的对象。"
            + _logical_stage_instruction(task_id)
        )
    is_first = bool(meta.get("is_first"))
    case_kind = str(meta.get("case_kind", "")).strip()
    if case_kind in {"verification_case", "validation_case"}:
        label = "VerificationCase" if case_kind == "verification_case" else "ValidationCase"
        requirement_ids = meta.get("requirement_ids")
        target_hint = (
            "payload.requirement_ids 必须恰好为 ["
            + ", ".join(str(item) for item in requirement_ids)
            + "]."
            if isinstance(requirement_ids, (list, tuple)) and requirement_ids
            else ""
        )
        return (
            f"当前是 V&V 第 {index}/{count} 个需求 Case 批次，只生成一个 {label}。"
            "只处理 requirement_worklist 中的一个 canonical Requirement；"
            f"Proposal 的 entities 只能包含一个 kind={case_kind} 的实体，"
            "不得生成另一种 V&V Case、Hazard 或 FailureMode。"
            + target_hint
            + "不要遗漏 requirement_ids；其余 function_ids、logical_component_ids、"
            "physical_ids 只填写当前上下文中与该 Requirement 对应的 canonical ID。"
            "计划字段必须是短句，procedure 只保留 3 步以内，不要输出解释性长文或重复上下文。"
        )
    risk_instruction = (
        "本批可以生成一个代表当前上下文异常分支的 hazard 和 failure_mode；"
        if is_first
        else "本批不得新增 hazard 或 failure_mode，只生成本批需求的 VerificationCase、ValidationCase 和必要更新；"
    )
    return (
        f"当前是 V&V 第 {index}/{count} 个需求批次。"
        "只处理 requirement_worklist 中的 canonical Requirement；不得为其它批次需求重复生成 V&V Case。"
        + risk_instruction
        + (
            "本批每个 Requirement 必须且只能生成 1 个 VerificationCase 和 1 个 ValidationCase；"
            "不要为同一 Requirement 生成第二个边界/异常 Case。"
            "为保证结构化输出完整且可落库，每个 VerificationCase 和 ValidationCase 的计划字段都用短句，"
            "每个字段尽量不超过 120 个中文字符，procedure 只保留 3 步以内；不要输出解释性长文或重复上下文。"
        )
    )


def _logical_stage_instruction(task_id: str) -> str:
    if task_id != "vertical.logical":
        return ""
    return (
        "Logical 阶段新增 State 时必须在 payload.owner_id 填写其所属的 canonical "
        "LogicalComponent ID（或本 Proposal 的 local_ref），并让该归属形成 decomposes 关系；"
        "新增 Interface 时必须在 payload.connected_component_ids 填写实际连接的 canonical "
        "LogicalComponent ID（或本 Proposal 的 local_ref），不得只写自由文本。"
    )


def _batch_descriptors(
    request: TaskExecutionRequest,
    batches: tuple[tuple[Mapping[str, object], ...], ...],
    model: GenerativeModel,
) -> tuple[tuple[tuple[Mapping[str, object], ...], str], ...]:
    """Expand remote assurance batches into one typed case per request.

    Verification and validation plans are both wide structured payloads.  A
    remote provider can reliably emit one plan, but may truncate a response
    containing both plans even when the requirement batch itself is a
    singleton.  Keep each requirement's two case types independently
    parallelizable and merge their typed patches at the existing boundary.
    """

    if (
        request.task_id != _VV_BATCH_TASK
        or getattr(model, "supports_vv_case_splitting", False) is not True
        or not any(batches)
    ):
        return tuple((batch, "") for batch in batches)
    return tuple(
        ((item,), case_kind)
        for batch in batches
        for item in batch
        for case_kind in ("verification_case", "validation_case")
    )


def _vv_case_kind(payload: Mapping[str, object]) -> str:
    metadata = payload.get("requirement_batch")
    if not isinstance(metadata, Mapping):
        return ""
    value = str(metadata.get("case_kind", "")).strip()
    return value if value in {"verification_case", "validation_case"} else ""


def _vv_case_contract(
    contract: Mapping[str, object],
    case_kind: str,
) -> Mapping[str, object]:
    """Narrow the provider schema to the one assurance case being generated."""

    allowed_kind = case_kind
    result = deepcopy(dict(contract))
    result["output_kinds"] = [allowed_kind]
    schemas = result.get("x-payload-schemas")
    if isinstance(schemas, Mapping):
        result["x-payload-schemas"] = {
            allowed_kind: deepcopy(schemas[allowed_kind])
        } if allowed_kind in schemas else {}
    properties = result.get("properties")
    if not isinstance(properties, Mapping):
        return result
    entities = properties.get("entities")
    if not isinstance(entities, Mapping):
        return result
    entity_items = entities.get("items")
    if not isinstance(entity_items, Mapping):
        return result
    payload_schema = (
        result.get("x-payload-schemas", {}).get(allowed_kind)
        if isinstance(result.get("x-payload-schemas"), Mapping)
        else None
    )
    if isinstance(payload_schema, Mapping):
        payload_schema = deepcopy(dict(payload_schema))
        required = payload_schema.get("required")
        required_fields = {
            str(item) for item in required
        } if isinstance(required, (list, tuple)) else set()
        required_fields.add("requirement_ids")
        payload_schema["required"] = sorted(required_fields)
        payload_properties = payload_schema.get("properties")
        if isinstance(payload_properties, Mapping):
            payload_properties = deepcopy(dict(payload_properties))
            payload_properties["requirement_ids"] = {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            }
            payload_schema["properties"] = payload_properties
        result["x-payload-schemas"] = {allowed_kind: payload_schema}
    narrowed_entity = deepcopy(dict(entity_items))
    narrowed_entity.pop("oneOf", None)
    narrowed_properties = dict(narrowed_entity.get("properties", {}))
    narrowed_properties["kind"] = {"const": allowed_kind}
    if isinstance(payload_schema, Mapping):
        narrowed_properties["payload"] = deepcopy(dict(payload_schema))
    narrowed_entity["properties"] = narrowed_properties
    narrowed_entity["required"] = ["local_ref", "kind", "name", "payload"]
    narrowed_entities = deepcopy(dict(entities))
    narrowed_entities["items"] = narrowed_entity
    narrowed_properties_root = dict(properties)
    narrowed_properties_root["entities"] = narrowed_entities
    result["properties"] = narrowed_properties_root
    return result


def _requirement_batches(
    request: TaskExecutionRequest,
    worklist: object,
    model: GenerativeModel,
    *,
    batch_size: int = _VERTICAL_BATCH_SIZE,
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
    effective_batch_size = int(batch_size)
    return tuple(
        entries[start : start + max(1, effective_batch_size)]
        for start in range(0, len(entries), max(1, effective_batch_size))
    )


def _r_stage_slices(
    request: TaskExecutionRequest,
    payload: Mapping[str, object],
    *,
    single_kind: bool = False,
) -> tuple[Mapping[str, object], ...]:
    """Plan bounded R backbone and one-Requirement closure payloads."""

    if request.task_id != "vertical.requirements":
        return (payload,)
    worklist = tuple(
        item
        for item in payload.get("requirement_worklist", ())
        if isinstance(item, Mapping) and str(item.get("requirement_id", "")).strip()
    )
    present_kinds = {
        item.kind.value
        for item in request.context_bundle.entities
        if item.meta.status is not EntityStatus.DEPRECATED
    }
    missing_kinds = set(_R_STAGE_KINDS) - present_kinds
    requirement_index = [
        {
            key: item[key]
            for key in ("requirement_id", "statement", "missing")
            if key in item
        }
        for item in worklist
    ]
    planned: list[Mapping[str, object]] = []
    for slice_kind, group in _R_BACKBONE_GROUPS:
        allowed_kinds = tuple(kind for kind in group if kind in missing_kinds)
        if not allowed_kinds:
            continue
        backbone_kinds = (
            tuple((kind,) for kind in allowed_kinds)
            if single_kind
            else (allowed_kinds,)
        )
        for backbone_kind in backbone_kinds:
            planned.append({
                **dict(payload),
                "requirement_worklist": [],
                "requirement_index": requirement_index,
                "r_slice": {
                    "slice_kind": slice_kind,
                    "allowed_kinds": list(backbone_kind),
                    "requirement_ids": [],
                },
            })
    for item in worklist:
        requirement_id = str(item["requirement_id"])
        planned.append({
            **dict(payload),
            "requirement_worklist": [dict(item)],
            "r_slice": {
                "slice_kind": "r_requirement",
                "allowed_kinds": [],
                "requirement_ids": [requirement_id],
            },
        })
    if not planned:
        return (payload,)
    count = len(planned)
    return tuple(
        {
            **item,
            "r_slice": {
                **dict(item["r_slice"]),
                "slice_index": index,
                "slice_count": count,
            },
        }
        for index, item in enumerate(planned, start=1)
    )


def _annotate_r_slice_failure(
    error: Exception,
    payload: Mapping[str, object],
) -> Exception:
    """Keep the failing R slice visible in the existing failure evidence."""

    metadata = payload.get("r_slice")
    if not isinstance(metadata, Mapping):
        return error
    label = (
        f"{metadata.get('slice_kind', 'unknown')}"
        f"[{metadata.get('slice_index', '?')}/{metadata.get('slice_count', '?')}]"
    )
    message = f"r_slice_failed={label}: {error}"
    common = {
        "code": getattr(error, "code", "r_slice_failed"),
        "raw_response": getattr(error, "raw_response", ""),
        "initial_raw_response": getattr(error, "initial_raw_response", ""),
        "schema_hash": getattr(error, "schema_hash", ""),
        "retry_count": getattr(error, "retry_count", 0),
        "provider_id": getattr(error, "provider_id", ""),
        "model_id": getattr(error, "model_id", ""),
    }
    if isinstance(error, StructuredOutputFailure):
        return StructuredOutputFailure(
            message,
            **common,
            finish_reason=getattr(error, "finish_reason", ""),
            usage=getattr(error, "usage", {}),
        )
    if isinstance(error, ProposalCompileFailure):
        return ProposalCompileFailure(
            message,
            **common,
            finish_reason=getattr(error, "finish_reason", ""),
            usage=getattr(error, "usage", {}),
        )
    if isinstance(error, TransportFailure):
        return TransportFailure(
            message,
            **common,
        )
    return error


def _narrow_r_backbone_payload(
    payload: Mapping[str, object],
    kind: str,
    offset: int,
    count: int,
) -> Mapping[str, object]:
    """Retry a wide backbone slice as one shared kind after truncation."""

    metadata = payload.get("r_slice")
    if not isinstance(metadata, Mapping):
        return payload
    narrowed = dict(metadata)
    narrowed["slice_kind"] = f"{metadata.get('slice_kind', 'r_backbone')}:{kind}"
    narrowed["allowed_kinds"] = [kind]
    narrowed["slice_index"] = int(metadata.get("slice_index", 0) or 0) + offset
    narrowed["slice_count"] = int(metadata.get("slice_count", count) or count)
    return {**dict(payload), "r_slice": narrowed}


def _r_slice_contract(
    contract: Mapping[str, object],
    payload: Mapping[str, object],
) -> Mapping[str, object]:
    """Narrow the R proposal schema to one bounded slice."""

    metadata = payload.get("r_slice")
    if not isinstance(metadata, Mapping):
        return contract
    result = deepcopy(dict(contract))
    slice_kind = str(metadata.get("slice_kind", ""))
    allowed_kinds = [str(item) for item in metadata.get("allowed_kinds", ())]
    result["output_kinds"] = allowed_kinds
    payload_schemas = result.get("x-payload-schemas")
    if isinstance(payload_schemas, Mapping):
        payload_kinds = (
            {EntityKind.REQUIREMENT.value}
            if slice_kind == "r_requirement"
            else set(allowed_kinds)
        )
        result["x-payload-schemas"] = {
            kind: deepcopy(schema)
            for kind, schema in payload_schemas.items()
            if kind in payload_kinds
        }
    properties = result.get("properties")
    if not isinstance(properties, Mapping):
        return result
    properties = deepcopy(dict(properties))
    entities = properties.get("entities")
    if isinstance(entities, Mapping):
        entities = deepcopy(dict(entities))
        entities["maxItems"] = len(allowed_kinds)
        entity_item = entities.get("items")
        if isinstance(entity_item, Mapping):
            entity_item = deepcopy(dict(entity_item))
            entity_properties = dict(entity_item.get("properties", {}))
            if allowed_kinds:
                entity_properties["kind"] = {
                    "enum": allowed_kinds,
                }
            entity_item["properties"] = entity_properties
            entities["items"] = entity_item
        properties["entities"] = entities
    relations = properties.get("relations")
    if isinstance(relations, Mapping):
        relations = deepcopy(dict(relations))
        relation_item = relations.get("items")
        if isinstance(relation_item, Mapping):
            relation_item = deepcopy(dict(relation_item))
            relation_properties = dict(relation_item.get("properties", {}))
            predicates = (
                {"derivedFrom", "decomposes"}
                if slice_kind == "r_requirement"
                else {
                    "hasConcern",
                    "participatesIn",
                    "occursIn",
                    "derivedFrom",
                    "decomposes",
                }
            )
            relation_properties["predicate"] = {
                "enum": sorted(predicates),
            }
            if slice_kind == "r_requirement" and metadata.get("requirement_ids"):
                relation_item["oneOf"] = [
                    {
                        "properties": {
                            "predicate": {"const": "derivedFrom"},
                            "source_ref": {
                                "const": str(metadata["requirement_ids"][0]),
                            },
                        },
                    },
                    {
                        "properties": {
                            "predicate": {"const": "decomposes"},
                        },
                    },
                ]
            relation_item["properties"] = relation_properties
            relations["items"] = relation_item
        relations["maxItems"] = 16 if slice_kind == "r_requirement" else 32
        properties["relations"] = relations
    if slice_kind == "r_requirement":
        updates = properties.get("updates")
        if isinstance(updates, Mapping):
            updates = deepcopy(dict(updates))
            updates["maxItems"] = 1
            update_item = updates.get("items")
            if isinstance(update_item, Mapping):
                update_item = deepcopy(dict(update_item))
                update_properties = dict(update_item.get("properties", {}))
                requirement_ids = metadata.get("requirement_ids", ())
                if requirement_ids:
                    update_properties["entity_id"] = {
                        "const": str(requirement_ids[0]),
                    }
                update_item["properties"] = update_properties
                updates["items"] = update_item
            properties["updates"] = updates
        deprecations = properties.get("deprecations")
        if isinstance(deprecations, Mapping):
            deprecations = deepcopy(dict(deprecations))
            deprecations["maxItems"] = 0
            properties["deprecations"] = deprecations
    result["properties"] = properties
    return result


def _r_slice_patch_policy(
    request: TaskExecutionRequest,
    payload: Mapping[str, object],
) -> PatchPolicy:
    """Restrict compiler write authority to the current R slice."""

    metadata = payload.get("r_slice")
    if not isinstance(metadata, Mapping):
        return request.patch_policy
    allowed_kinds = frozenset(
        EntityKind(str(item))
        for item in metadata.get("allowed_kinds", ())
    )
    if metadata.get("slice_kind") == "r_requirement":
        # The provider-facing schema forbids entity additions. Keep the
        # Requirement kind in the compiler policy so updates to the existing
        # canonical Requirement remain in scope without reopening the broad R
        # write policy.
        allowed_kinds = frozenset({EntityKind.REQUIREMENT})
    predicates = (
        frozenset({RelationPredicate.DERIVED_FROM, RelationPredicate.DECOMPOSES})
        if metadata.get("slice_kind") == "r_requirement"
        else frozenset({
            RelationPredicate.HAS_CONCERN,
            RelationPredicate.PARTICIPATES_IN,
            RelationPredicate.OCCURS_IN,
            RelationPredicate.DERIVED_FROM,
            RelationPredicate.DECOMPOSES,
        })
    )
    return replace(
        request.patch_policy,
        writable_kinds=allowed_kinds,
        allowed_predicates=predicates,
    )


def _request_for_working_graph(
    request: TaskExecutionRequest,
    graph: ModelGraph,
) -> TaskExecutionRequest:
    context = replace(
        request.context_bundle,
        revision=graph.revision,
        entities=graph.entities,
        relations=graph.relations,
    )
    return replace(request, context_bundle=context)


def _r_payload_for_request(
    request: TaskExecutionRequest,
    payload: Mapping[str, object],
) -> Mapping[str, object]:
    """Refresh compact context after a temporary R slice is compiled."""

    context = request.context_bundle
    context_payload = {
        "project_id": context.project_id,
        "revision": context.revision,
        "token_estimate": context.token_estimate,
        "entities": [
            _model_entity(item, compact=True)
            for item in context.entities
        ],
        "relations": [
            _model_relation(item, compact=True)
            for item in context.relations
        ],
    }
    return {
        **dict(payload),
        "context": context_payload,
        "context_hash": canonical_hash(context),
    }


def _rebase_patch(patch: Patch, expected_revision: int) -> Patch:
    """Keep a compiled temporary patch at the original CAS boundary."""

    return Patch(
        patch.id,
        patch.project_id,
        patch.task_id,
        patch.operations,
        patch.reason,
        expected_revision,
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
    context_entity_ids = {
        str(entity.get("id", ""))
        for entity in entities
        if isinstance(entity, Mapping) and str(entity.get("id", ""))
    }
    visible_ids = _batch_context_ids(
        request,
        batch,
        entities,
        context.get("relations"),
        requirement_ids,
    ) & context_entity_ids
    scoped_entities = [
        entity
        for entity in entities
        if not isinstance(entity, Mapping)
        or str(entity.get("id", "")) in visible_ids
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


def _batch_context_ids(
    request: TaskExecutionRequest,
    batch: tuple[Mapping[str, object], ...] | list[Mapping[str, object]],
    entities: tuple[object, ...] | list[object],
    relations: object,
    requirement_ids: set[str],
) -> set[str]:
    """Select the canonical trace slice needed by one parallel batch.

    A vertical batch already carries its exact Requirement worklist. Keeping
    every non-Requirement entity in every batch makes later L/P/V&V prompts
    grow with the whole project and can cross a provider context window. Start
    from the batch's current typed targets, retain the shared System, then add
    one-hop graph neighbors so each provider call still has enough upstream
    and downstream grounding to create typed links.
    """

    entity_by_id = {
        str(entity.get("id", "")): entity
        for entity in entities
        if isinstance(entity, Mapping) and str(entity.get("id", ""))
    }
    visible_ids = set(requirement_ids)
    for item in batch:
        current = item.get("current") if isinstance(item, Mapping) else None
        if not isinstance(current, Mapping):
            continue
        for field in _VERTICAL_CURRENT_FIELDS:
            values = current.get(field, ())
            if isinstance(values, (list, tuple)):
                visible_ids.update(
                    str(value)
                    for value in values
                    if str(value).strip() in entity_by_id
                )

    # The system definition is shared context, not batch-owned work. Retain
    # it explicitly even when the current slice has no direct relation to it.
    # Keep the batch roots separate so adding the shared System does not pull
    # every other Requirement back in through a reverse relation.
    seed_ids = set(visible_ids)
    visible_ids.update(
        entity_id
        for entity_id, entity in entity_by_id.items()
        if entity.get("kind") == EntityKind.SYSTEM.value
    )

    if isinstance(relations, (list, tuple)):
        neighbor_ids = set(visible_ids)
        for relation in relations:
            if not isinstance(relation, Mapping):
                continue
            source_id = str(relation.get("source_id", ""))
            target_id = str(relation.get("target_id", ""))
            if source_id in seed_ids and target_id in entity_by_id:
                neighbor_ids.add(target_id)
            if target_id in seed_ids and source_id in entity_by_id:
                neighbor_ids.add(source_id)
        visible_ids.update(neighbor_ids)
    return visible_ids


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


def _is_wide_requirement_batch(payload: Mapping[str, object]) -> bool:
    batch = payload.get("requirement_batch")
    worklist = payload.get("requirement_worklist")
    return isinstance(batch, Mapping) and isinstance(worklist, (list, tuple)) and len(worklist) > 1


def _batch_token_budget(
    request: TaskExecutionRequest,
    payload: Mapping[str, object],
    *,
    singleton_fallback: bool = False,
    batch_output_token_budget: int = _VERTICAL_BATCH_OUTPUT_TOKEN_BUDGET,
    singleton_output_token_budget: int = _VERTICAL_SINGLETON_OUTPUT_TOKEN_BUDGET,
) -> int:
    """Keep multi-requirement provider calls bounded without shrinking R output."""

    batch = payload.get("requirement_batch")
    if request.task_id not in _VERTICAL_BATCH_TASKS or not isinstance(batch, Mapping):
        return request.token_budget
    if singleton_fallback:
        return min(request.token_budget, singleton_output_token_budget)
    return min(request.token_budget, batch_output_token_budget)


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
