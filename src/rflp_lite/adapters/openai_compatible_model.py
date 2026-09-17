"""Adapter for OpenAI-compatible chat completion endpoints."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, MutableMapping

from rflp_lite.adapters.llm_client import (
    _bounded_max_tokens,
    _fit_context_window,
    _is_native_ollama,
    chat_completion,
)
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import AdapterFailure, StructuredOutputFailure, TransportFailure
from rflp_lite.ports.generative_model import (
    GenerationRequest,
    GenerationResponse,
    add_simplified_chinese_instruction,
)
from rflp_lite.ports.token_budget import estimate_tokens


_REPAIR_FAILURE = "LLM response is not valid JSON after one repair"
_PROVIDER_SCHEMA_META_KEYS = frozenset({
    "schema_id",
    "output_kinds",
    "patch_policy",
    "validators",
    "max_attempts",
})
# vLLM counts chat wrappers and structured-output grammar tokens with its own
# tokenizer.  The extra bounded margin keeps a 16k endpoint from rejecting a
# request that the provider-neutral estimator considers just inside the limit.
_OPENAI_CONTEXT_TOKEN_SAFETY_MARGIN = 5376


class _InvalidStructuredResponse(ValueError):
    """The provider returned JSON that cannot be accepted for this request."""

    def __init__(self, message: str, *, code: str = "schema_validation") -> None:
        self.code = code
        super().__init__(message)


def _provider_call_config(
    config: Mapping[str, object],
    request: GenerationRequest,
    *,
    native_ollama: bool,
    structured_output_mode: str,
) -> tuple[Mapping[str, object], int, int]:
    call_config = dict(config)
    provider_response_format: object | None = None
    if native_ollama:
        if structured_output_mode != "none":
            call_config["json_schema"] = _ollama_transport_schema(request.response_schema)
    elif str(call_config.get("structured_output_mode", "json_schema")).casefold() != "none":
        provider_response_format = call_config.get("response_format")
        if provider_response_format is None:
            provider_response_format = _openai_response_format(
                request.lens_id,
                request.response_schema,
                structured_output_mode,
            )
            call_config["response_format"] = provider_response_format
    extra_tokens = (
        estimate_tokens(json.dumps(provider_response_format, ensure_ascii=False))
        if provider_response_format is not None
        else 0
    )
    safety_margin = (
        _OPENAI_CONTEXT_TOKEN_SAFETY_MARGIN
        if provider_response_format is not None
        else 256
    )
    return call_config, extra_tokens, safety_margin


def _openai_response_format(
    lens_id: str,
    response_schema: Mapping[str, object],
    mode: str,
) -> Mapping[str, object]:
    if mode.casefold() in {"json_object", "json"}:
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": lens_id.replace("-", "_"),
            "strict": True,
            "schema": _provider_transport_schema(response_schema),
        },
    }


def _provider_transport_schema(value: object) -> object:
    """Remove schema constructs unsupported by the remote grammar compiler.

    The application keeps the complete contract for post-response validation.
    Some OpenAI-compatible vLLM builds cannot compile nested ``oneOf`` and
    silently weaken the generated grammar. A transport copy with the common
    envelope and ordinary JSON Schema constraints intact lets the provider
    enforce the stable shape; kind-specific payload rules remain enforced by
    ``_parse_and_validate`` and the TaskProposal compiler.
    """

    if isinstance(value, Mapping):
        return {
            str(key): _provider_transport_schema(item)
            for key, item in value.items()
            if key != "oneOf"
            and key not in _PROVIDER_SCHEMA_META_KEYS
            and not str(key).startswith("x-")
        }
    if isinstance(value, list):
        return [_provider_transport_schema(item) for item in value]
    return value


def _ollama_transport_schema(value: object) -> object:
    """Compile a provider-safe copy without weakening application validation.

    Ollama 0.32.x rejects a grammar containing ``maxLength: 2000`` even though
    the same object schema is valid JSON Schema.  The canonical schema remains
    on the request and is still used for post-response validation; only the
    native Ollama grammar copy omits that provider-only constraint.
    """

    if isinstance(value, dict):
        return {
            str(key): _ollama_transport_schema(item)
            for key, item in value.items()
            if not (
                key == "maxLength"
                and isinstance(item, int)
                and item >= 2000
            )
        }
    if isinstance(value, list):
        return [_ollama_transport_schema(item) for item in value]
    return value


def _repair_input(request: GenerationRequest) -> Mapping[str, object]:
    """Keep structural retries small enough to leave room for a full result."""

    if not request.lens_id.startswith("vertical."):
        return request.user_payload
    retained = {
        "task_id",
        "methodology_version",
        "requirement_worklist",
        # Preserve the vertical runtime's batch boundary during repair.  If
        # this metadata is dropped, a malformed batch retry may regenerate the
        # whole worklist and exceed the provider's output budget.
        "requirement_batch",
    }
    result = {
        key: value
        for key, value in request.user_payload.items()
        if key in retained
    }
    context = request.user_payload.get("context")
    if isinstance(context, Mapping):
        result["context"] = _compact_repair_context(context)
    return result


def _compact_repair_context(context: Mapping[str, object]) -> Mapping[str, object]:
    """Keep canonical identity evidence without resending the full graph."""

    entities = context.get("entities")
    compact_entities: list[Mapping[str, object]] = []
    if isinstance(entities, (list, tuple)):
        for entity in entities:
            if not isinstance(entity, Mapping):
                continue
            compact = {
                key: entity[key]
                for key in ("id", "kind", "name", "status")
                if key in entity
            }
            payload = entity.get("payload")
            if isinstance(payload, Mapping):
                fields_by_kind = {
                    "requirement": (
                        "statement", "level", "type", "obligation",
                        "verification_method", "functional_behavior_ids",
                    ),
                    "function": ("decomposition",),
                    "functional_flow": (
                        "source_function_ids", "target_function_ids",
                    ),
                    "functional_scenario": ("function_ids",),
                    "logical_component": (
                        "function_id", "responsibility", "dependencies",
                    ),
                    "physical_block": (
                        "logical_id", "source_logical_ids", "source_function_ids",
                    ),
                    "verification_case": (
                        "requirement_ids", "function_ids", "logical_component_ids",
                        "physical_ids",
                    ),
                    "validation_case": (
                        "requirement_ids", "scenario_ids", "function_ids",
                    ),
                }
                fields = fields_by_kind.get(str(entity.get("kind")), ())
                compact_payload = {
                    key: payload[key] for key in fields if key in payload
                }
                if compact_payload:
                    compact["payload"] = compact_payload
            compact_entities.append(compact)
    relations = context.get("relations")
    compact_relations = []
    if isinstance(relations, (list, tuple)):
        for relation in relations:
            if not isinstance(relation, Mapping):
                continue
            compact_relations.append({
                key: relation[key]
                for key in ("source_id", "predicate", "target_id")
                if key in relation
            })
    return {
        key: context[key]
        for key in ("project_id", "revision")
        if key in context
    } | {"entities": compact_entities, "relations": compact_relations}


def _vertical_repair_instruction(task_id: str) -> str:
    rules = {
        "vertical.requirements": (
            "entities 只能使用当前缺失的 operational/R 类型；不要输出 function、"
            "logical_component、physical_block 或 V&V 类型。"
        ),
        "vertical.functional": (
            "entities 只能使用 function、functional_flow、functional_scenario、requirement；"
            "不得把 context.entities 中的 Requirement 复制到 entities。"
        ),
        "vertical.logical": (
            "entities 只能使用 logical_component、interface、state；"
            "不得输出 Requirement、Function 或 PhysicalBlock。"
        ),
        "vertical.physical": (
            "entities 只能使用 physical_block、requirement；不得输出其它类型。"
        ),
        "vertical.verification_validation": (
            "entities 只能使用 verification_case、validation_case、hazard、failure_mode、requirement；"
            "不得输出其它类型。"
        ),
    }
    return rules.get(task_id, "")


def _vertical_batch_repair_instruction(request: GenerationRequest) -> str:
    """Keep a vertical structural retry scoped to its original requirement batch."""

    if not request.lens_id.startswith("vertical."):
        return ""
    batch = request.user_payload.get("requirement_batch")
    if not isinstance(batch, Mapping):
        return ""
    index = batch.get("index")
    count = batch.get("count")
    return (
        f"这是当前阶段第 {index}/{count} 个需求批次；修复时只处理本批 "
        "requirement_worklist，禁止扩展到其它批次或重新生成完整 worklist。"
    )


def _is_wide_vertical_batch(request: GenerationRequest) -> bool:
    """Let the runtime split a failed batch before spending another provider call."""

    if not request.lens_id.startswith("vertical."):
        return False
    batch = request.user_payload.get("requirement_batch")
    worklist = request.user_payload.get("requirement_worklist")
    return isinstance(batch, Mapping) and isinstance(worklist, (list, tuple)) and len(worklist) > 1


def _normalize_vertical_payload(
    payload: object,
    response_schema: Mapping[str, object],
) -> object:
    """Keep useful vertical JSON while normalizing harmless wire omissions.

    The vertical endpoint is deliberately validated twice: this function only
    removes transport noise and fills fields whose meaning is unambiguous;
    the canonical JSON schema and proposal compiler remain authoritative for
    semantic content.
    """

    if not isinstance(payload, dict):
        return payload
    properties = response_schema.get("properties")
    if not isinstance(properties, Mapping):
        return payload
    result = {
        str(key): value
        for key, value in payload.items()
        if key in properties
    }
    for field in ("entities", "relations", "updates", "deprecations"):
        if field not in result:
            result[field] = []
    if not isinstance(result.get("reason"), str) or not result["reason"].strip():
        result["reason"] = "保留远程模型返回的可用增量"

    entity_schema = properties.get("entities")
    entity_item = _array_item_schema(entity_schema)
    entity_properties = _schema_properties(entity_item)
    raw_entities = payload.get("entities")
    if isinstance(raw_entities, (list, tuple)) and entity_properties is not None:
        normalized_entities = []
        for entity in raw_entities:
            if not isinstance(entity, Mapping):
                continue
            normalized = {
                str(key): value
                for key, value in entity.items()
                if key in entity_properties
            }
            if not all(key in normalized for key in ("local_ref", "name", "payload")):
                continue
            kind = str(normalized.get("kind", "")).strip()
            entity_payload = normalized.get("payload")
            if isinstance(entity_payload, Mapping):
                normalized["payload"] = _normalize_vertical_entity_payload(
                    kind,
                    entity_payload,
                    entity_item,
                    normalized.get("name"),
                )
            normalized_entities.append(normalized)
        result["entities"] = normalized_entities

    relation_schema = properties.get("relations")
    relation_properties = _array_item_properties(relation_schema)
    allowed_predicates = _array_item_enum(relation_schema, "predicate")
    relations = payload.get("relations")
    if isinstance(relations, (list, tuple)) and relation_properties is not None:
        normalized_relations = []
        for relation in relations:
            if not isinstance(relation, Mapping):
                continue
            predicate = relation.get("predicate")
            if allowed_predicates and predicate not in allowed_predicates:
                continue
            normalized = {
                str(key): value
                for key, value in relation.items()
                if key in relation_properties
            }
            normalized.setdefault("evidence_ids", [])
            normalized_relations.append(normalized)
        result["relations"] = normalized_relations
    return result


def _array_item_schema(schema: object) -> Mapping[str, object] | None:
    if not isinstance(schema, Mapping):
        return None
    items = schema.get("items")
    return items if isinstance(items, Mapping) else None


def _schema_properties(schema: object) -> Mapping[str, object] | None:
    if not isinstance(schema, Mapping):
        return None
    properties = schema.get("properties")
    return properties if isinstance(properties, Mapping) else None


def _entity_payload_schema(
    entity_schema: Mapping[str, object] | None,
    kind: str,
) -> Mapping[str, object] | None:
    if entity_schema is None:
        return None
    properties = _schema_properties(entity_schema)
    if properties is not None:
        direct = properties.get("payload")
        if isinstance(direct, Mapping) and len(properties) <= 4:
            return direct
    branches = entity_schema.get("oneOf")
    if not isinstance(branches, (list, tuple)):
        return None
    for branch in branches:
        branch_properties = _schema_properties(branch)
        kind_schema = branch_properties.get("kind") if branch_properties else None
        if not isinstance(kind_schema, Mapping) or kind_schema.get("const") != kind:
            continue
        payload_schema = branch_properties.get("payload") if branch_properties else None
        return payload_schema if isinstance(payload_schema, Mapping) else None
    return None


def _normalize_vertical_entity_payload(
    kind: str,
    payload: Mapping[str, object],
    entity_schema: Mapping[str, object] | None,
    entity_name: object,
) -> Mapping[str, object]:
    """Normalize only fields that are explicit equivalents in the wire form."""

    payload_schema = _entity_payload_schema(entity_schema, kind)
    payload_properties = _schema_properties(payload_schema)
    source = dict(payload)
    if (
        isinstance(payload_schema, Mapping)
        and payload_schema.get("additionalProperties") is False
        and payload_properties is not None
    ):
        source = {
            str(key): value
            for key, value in source.items()
            if key in payload_properties
        }
    if kind == "system":
        source.setdefault(
            "mission",
            str(payload.get("description") or entity_name or "系统目标").strip(),
        )
        source.setdefault("system_boundary", {"inside": [], "outside": []})
        source.setdefault("objectives", [])
        source.setdefault("environment_assumptions", [])
        source.setdefault("exclusions", [])
        source.setdefault("open_questions", [])
    elif kind == "concern":
        source.setdefault(
            "topic",
            str(payload.get("description") or entity_name or "待澄清关注点").strip(),
        )
    elif kind == "requirement" and "statement" not in source:
        source["statement"] = str(payload.get("description") or entity_name or "待澄清需求").strip()
    elif kind == "logical_component":
        partition_basis = source.get("partition_basis")
        if isinstance(partition_basis, Mapping):
            source["partition_basis"] = _wire_text(partition_basis)
        for field in (
            "dependencies",
            "functional_flow_ids",
            "cross_component_flow_ids",
            "shared_state_ids",
            "source_context_ids",
        ):
            if field in source:
                source[field] = _wire_string_list(source[field])
        shared_state = source.get("shared_state")
        if isinstance(shared_state, (list, tuple)):
            existing_state_ids = source.get("shared_state_ids")
            shared_state_ids = (
                list(existing_state_ids)
                if isinstance(existing_state_ids, (list, tuple))
                else []
            )
            normalized_state = []
            for item in shared_state:
                if isinstance(item, Mapping):
                    item_id = str(item.get("id") or "").strip()
                    if item_id and item_id not in shared_state_ids:
                        shared_state_ids.append(item_id)
                    normalized_state.append(
                        str(item.get("name") or item.get("description") or _wire_text(item)).strip()
                    )
                elif str(item).strip():
                    normalized_state.append(str(item).strip())
            source["shared_state"] = normalized_state
            if shared_state_ids:
                source["shared_state_ids"] = shared_state_ids
        safety_isolation = source.get("safety_isolation")
        if isinstance(safety_isolation, Mapping):
            source["safety_isolation"] = [safety_isolation]
        for field in ("timing_constraints", "safety_isolation", "safety_constraints"):
            if isinstance(source.get(field), Mapping):
                source[field] = [source[field]]
            elif field in source and not isinstance(source[field], (list, tuple)):
                source[field] = [source[field]]
        rationale = source.get("architecture_rationale")
        if isinstance(rationale, Mapping):
            reasoning = source.get("architecture_reasoning")
            if isinstance(reasoning, Mapping):
                source["architecture_reasoning"] = {
                    **dict(reasoning),
                    **dict(rationale),
                }
            else:
                source["architecture_reasoning"] = dict(rationale)
            source["architecture_rationale"] = _wire_text(rationale)
    elif kind == "state":
        for field in ("values", "transitions"):
            if field in source:
                source[field] = _wire_string_list(source[field])
    elif kind == "function":
        _normalize_function_payload(source)
    elif kind in {"functional_flow", "functional_scenario"}:
        for field in ("source_function_ids", "target_function_ids", "function_ids"):
            if field in source:
                source[field] = _wire_string_list(source[field])
    elif kind == "physical_block":
        for field in ("candidate_type", "selection_rationale"):
            if isinstance(source.get(field), Mapping):
                source[field] = _wire_text(source[field])
        if "selection_rationale" not in source:
            rationale = source.get("rationale") or source.get("feasibility_reasoning")
            if isinstance(rationale, Mapping):
                source["selection_rationale"] = _wire_text(rationale)
            elif str(rationale or "").strip():
                source["selection_rationale"] = str(rationale).strip()
            else:
                source["selection_rationale"] = (
                    "根据当前逻辑职责选择可部署的物理候选"
                )
        if isinstance(source.get("propagated_constraints"), (list, tuple)):
            source["propagated_constraints"] = {
                "items": list(source["propagated_constraints"]),
            }
        for field in (
            "source_logical_ids", "source_function_ids", "source_requirement_ids",
            "alternatives", "open_questions",
        ):
            if field in source:
                source[field] = _wire_string_list(source[field])
        _normalize_physical_scalar_fields(source)
    elif kind in {"verification_case", "validation_case"}:
        for field in (
            "method", "verification_objective", "precondition", "test_condition",
            "input", "stimulus", "procedure", "expected_result", "pass_criteria",
        ):
            if field in source:
                source[field] = _wire_scalar_text(source[field])
        for field in (
            "requirement_ids", "scenario_ids", "activity_ids", "function_ids",
            "logical_component_ids", "physical_ids", "covered_branches",
        ):
            if field in source:
                source[field] = _wire_string_list(source[field])
    elif kind in {"hazard", "failure_mode"}:
        for field in (
            "requirement_ids", "scenario_ids", "activity_ids", "function_ids",
            "logical_component_ids", "physical_ids", "covered_branches",
        ):
            if field in source:
                source[field] = _wire_string_list(source[field])
    return source


def _normalize_function_payload(source: MutableMapping[str, object]) -> None:
    """Map common provider function wording to the typed required field."""

    decomposition = source.get("decomposition")
    if decomposition is None:
        decomposition = source.get("purpose") or source.get("behavior")
        if decomposition is not None:
            source["decomposition"] = decomposition
    if isinstance(decomposition, Mapping):
        source["decomposition"] = _wire_text(decomposition)


def _wire_string_list(value: object) -> list[str]:
    """Normalize scalar/object list members for a string-array schema slot."""

    values = value if isinstance(value, (list, tuple)) else [value]
    result = []
    for item in values:
        if isinstance(item, Mapping):
            text = str(
                item.get("id")
                or item.get("name")
                or item.get("description")
                or item.get("option")
                or item.get("label")
                or item.get("value")
                or ""
            ).strip()
        else:
            text = str(item or "").strip()
        if text:
            result.append(text)
    return result


def _normalize_physical_scalar_fields(source: MutableMapping[str, object]) -> None:
    """Fit structured measurements into the physical payload scalar subset."""

    for field in (
        "mass_kg", "power_w", "compute", "memory_mb", "latency_ms",
        "bandwidth_mbps", "cost", "thermal", "reliability",
        "availability", "endurance_h",
    ):
        if field in source:
            source[field] = _wire_scalar_text(source[field])


def _wire_text(value: Mapping[str, object]) -> str:
    """Keep a structured provider value in a scalar schema slot."""

    for key in ("rationale", "reason", "description", "basis"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True)


def _wire_scalar_text(value: object) -> object:
    """Normalize structured/list wire values into a scalar text field."""

    if isinstance(value, Mapping):
        return _wire_text(value)
    if isinstance(value, (list, tuple)):
        return "；".join(_wire_string_list(value))
    if isinstance(value, bool):
        return str(value).lower()
    return value


def _array_item_properties(schema: object) -> Mapping[str, object] | None:
    return _schema_properties(_array_item_schema(schema))


def _array_item_enum(schema: object, field: str) -> frozenset[object]:
    properties = _array_item_properties(schema)
    if properties is None:
        return frozenset()
    field_schema = properties.get(field)
    if not isinstance(field_schema, Mapping):
        return frozenset()
    values = field_schema.get("enum")
    return frozenset(values) if isinstance(values, (list, tuple, set)) else frozenset()


def _recover_json_array(text: str, start: int) -> list[object] | None:
    """Recover complete items from an array whose final item was truncated."""

    if start >= len(text) or text[start] != "[":
        return None
    decoder = json.JSONDecoder()
    cursor = start + 1
    items: list[object] = []
    while cursor < len(text):
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if cursor < len(text) and text[cursor] == "]":
            return items
        if cursor < len(text) and text[cursor] == ",":
            cursor += 1
            continue
        try:
            item, end = decoder.raw_decode(text, cursor)
        except json.JSONDecodeError:
            break
        items.append(item)
        cursor = end
    return items or None


def _recover_vertical_json(raw: object) -> Mapping[str, object] | None:
    """Recover a usable TaskProposal prefix before asking the provider again.

    Qwen/vLLM can stop after emitting several complete entities while the last
    relation or update is still open.  Complete array items are safe to keep;
    the incomplete tail is intentionally discarded and must still pass the
    normal schema/compiler path.
    """

    text = str(raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
            if text.casefold().startswith("json"):
                text = text[4:].lstrip()
    start = text.find("{")
    if start < 0:
        return None
    decoder = json.JSONDecoder()
    cursor = start + 1
    recovered = {}
    array_fields = {"entities", "relations", "updates", "deprecations"}
    while cursor < len(text):
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if cursor < len(text) and text[cursor] == ",":
            cursor += 1
            continue
        if cursor < len(text) and text[cursor] == "}":
            break
        try:
            key, key_end = decoder.raw_decode(text, cursor)
        except json.JSONDecodeError:
            break
        if not isinstance(key, str):
            break
        cursor = key_end
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if cursor >= len(text) or text[cursor] != ":":
            break
        value_start = cursor + 1
        while value_start < len(text) and text[value_start].isspace():
            value_start += 1
        try:
            value, value_end = decoder.raw_decode(text, value_start)
        except json.JSONDecodeError:
            if key in array_fields:
                items = _recover_json_array(text, value_start)
                if items:
                    recovered[key] = items
            break
        recovered[key] = value
        cursor = value_end
    if not any(
        isinstance(recovered.get(field), list) and recovered[field]
        for field in array_fields
    ):
        return None
    for field in array_fields:
        recovered.setdefault(field, [])
    recovered.setdefault("reason", "保留远程模型返回的可用增量")
    return recovered


class OpenAICompatibleModel:
    """Translate the stable application request into one JSON-only model call."""

    supports_requirement_batching = True
    # The adapter is stateless per request, so independent requirement batches
    # can use the provider's in-flight request slots.  StructuredModelRuntime
    # still compiles and validates the merged patch only after every batch has
    # returned, preserving the single CAS boundary.
    supports_parallel_requirement_batching = True
    # The product vertical path needs one bounded completion pass: a provider
    # can return a structurally valid proposal that omits one required R/F/L/P
    # semantic link.  ModelGenerationService feeds the exact completion gap
    # back once, then continues with the usable partial result if the retry
    # endpoint is unavailable. This is completion-oriented feedback, not a
    # stability experiment or an open-ended retry loop.
    automatic_vertical_stage_feedback = True
    supports_controller_proposals = True

    def __init__(
        self,
        config: dict[str, object],
        *,
        complete: Callable[..., str] = chat_completion,
    ) -> None:
        self._config = dict(config)
        self._complete = complete
        configured_feedback = self._config.get("vertical_feedback")
        if not isinstance(configured_feedback, bool):
            configured_feedback = str(
                self._config.get("model_location", "local")
            ).casefold() != "remote"
        # A remote profile normally uses the typed completion bridge after one
        # proposal pass.  Keep the feedback pass opt-in for slower providers.
        self.automatic_vertical_stage_feedback = configured_feedback
        self.automatic_vertical_stage_completion_bridge = True
        try:
            self.vertical_batch_size = max(
                1,
                min(
                    32,
                    int(
                        self._config.get(
                            "vertical_batch_size",
                            2,
                        )
                    ),
                ),
            )
        except (TypeError, ValueError):
            self.vertical_batch_size = 2
        try:
            self.vertical_batch_output_token_budget = max(
                256,
                int(
                    self._config.get(
                        "vertical_batch_output_tokens",
                        3072,
                    )
                ),
            )
        except (TypeError, ValueError):
            self.vertical_batch_output_token_budget = 3072
        try:
            configured_parallelism = int(
                self._config.get(
                    "max_parallel_requests",
                    2 if str(self._config.get("model_location", "local")).casefold() == "remote" else 4,
                )
            )
        except (TypeError, ValueError):
            configured_parallelism = 2
        self.max_parallel_requests = max(1, min(4, configured_parallelism))

    @staticmethod
    def _parse_json(raw: object) -> object:
        text = str(raw or "").strip()
        if not text:
            raise _InvalidStructuredResponse("empty content", code="json_decode")
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) < 3 or not lines[-1].strip().startswith("```"):
                raise _InvalidStructuredResponse("unclosed JSON fence", code="json_decode")
            text = "\n".join(lines[1:-1]).strip()
            if text.casefold().startswith("json"):
                text = text[4:].lstrip()
        try:
            value = json.loads(text)
        except (TypeError, json.JSONDecodeError) as exc:
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start:
                raise _InvalidStructuredResponse("no complete JSON object", code="json_decode") from exc
            try:
                value = json.loads(text[start : end + 1])
            except (TypeError, json.JSONDecodeError) as boundary_exc:
                raise _InvalidStructuredResponse("invalid JSON object", code="json_decode") from boundary_exc
        return value

    @classmethod
    def _parse_and_validate(
        cls,
        raw: object,
        response_schema: dict[str, object],
        *,
        normalize_vertical: bool = False,
    ) -> dict[str, object]:
        payload = cls._parse_json(raw)
        if normalize_vertical:
            payload = _normalize_vertical_payload(payload, response_schema)
        # Keep the older requirements/ai provider shape usable while the
        # application still receives the strict object envelope.  This is
        # deliberately limited to schemas whose only contract is an `items`
        # array; six-block schemas still require their full envelope.
        if isinstance(payload, list) and response_schema.get("type") == "object":
            properties = response_schema.get("properties")
            required = response_schema.get("required")
            if isinstance(properties, dict) and set(properties) == {"items"} and required == ["items"]:
                payload = {"items": payload}
        if not isinstance(payload, dict):
            raise _InvalidStructuredResponse("response must be an object", code="schema_validation")
        try:
            import jsonschema
        except ImportError as exc:
            raise AdapterFailure("JSON schema validation is unavailable") from exc
        try:
            jsonschema.validate(instance=payload, schema=response_schema)
        except jsonschema.ValidationError as exc:
            path = ".".join(str(item) for item in exc.absolute_path)
            detail = f": {exc.message}" + (f" at {path}" if path else "")
            raise _InvalidStructuredResponse(
                "response does not match schema" + detail,
                code="schema_validation",
            ) from exc
        except jsonschema.SchemaError as exc:
            raise AdapterFailure("LLM response schema is invalid") from exc
        return payload

    @staticmethod
    def _ensure_complete(raw: object) -> None:
        if str(getattr(raw, "done_reason", "")).casefold() in {"length", "max_tokens"}:
            raise _InvalidStructuredResponse("provider output was truncated", code="truncated")

    def _repair_budget(self, max_tokens: int | None, raw: object) -> int | None:
        if max_tokens is None:
            return None
        if str(getattr(raw, "done_reason", "")).casefold() not in {"length", "max_tokens"}:
            return max_tokens
        try:
            local_cap = int(
                self._config.get(
                    "max_output_tokens",
                    self._config.get("local_max_tokens", 0),
                )
                or 0
            )
        except (TypeError, ValueError):
            local_cap = 0
        expanded = max_tokens * 2
        return min(local_cap, expanded) if local_cap > max_tokens else max_tokens

    @staticmethod
    def _repair_messages(
        request: GenerationRequest, raw: object, *, include_schema: bool = True
    ) -> list[dict[str, str]]:
        max_items = request.user_payload.get("max_items")
        if not isinstance(max_items, int) or max_items < 1:
            max_items = 32
        envelope = {
            "input": _repair_input(request),
            "invalid_response": str(raw or "")[:4000],
        }
        if include_schema:
            envelope["response_schema"] = request.response_schema
        return [
            {
                "role": "system",
                "content": add_simplified_chinese_instruction(
                    f"重新生成完整的 JSON 分析结果，最多返回 {max_items} 项；"
                    "保留有效内容，修复 TaskProposal 结构；已有 canonical 实体不要重复新增，"
                    "使用最小数量的 entities、updates 和 relations 完成闭合；"
                    + _vertical_batch_repair_instruction(request)
                    + _vertical_repair_instruction(request.lens_id)
                    + "不要解释，也不要用空数组规避任务。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(envelope, ensure_ascii=False, sort_keys=True),
            },
        ]


    def _validate_or_repair(
        self,
        request: GenerationRequest,
        raw: object,
        call_config: Mapping[str, object],
        max_tokens: int,
        *,
        native_ollama: bool,
        structured_output_mode: str,
        transport_extra_tokens: int,
        transport_safety_margin: int,
    ) -> tuple[Mapping[str, object], bool, object]:
        repaired = False
        recovered = False
        final_raw = raw
        try:
            self._ensure_complete(raw)
            payload = self._parse_and_validate(
                raw,
                request.response_schema,
                normalize_vertical=request.lens_id.startswith("vertical."),
            )
            return payload, repaired, final_raw
        except _InvalidStructuredResponse as initial_error:
            if request.lens_id.startswith("vertical."):
                recovered_payload = _recover_vertical_json(raw)
                if recovered_payload is not None:
                    try:
                        payload = self._parse_and_validate(
                            json.dumps(recovered_payload, ensure_ascii=False),
                            request.response_schema,
                            normalize_vertical=True,
                        )
                        recovered = True
                        repaired = True
                    except _InvalidStructuredResponse:
                        pass
            if recovered:
                return payload, repaired, final_raw
            if _is_wide_vertical_batch(request):
                raise StructuredOutputFailure(
                    f"{_REPAIR_FAILURE}: {initial_error}",
                    code=initial_error.code,
                    raw_response=str(raw or ""),
                    initial_raw_response=str(raw or ""),
                    schema_hash=canonical_hash(request.response_schema),
                    provider_id=str(self._config.get("id", self._config.get("label", "openai-compatible"))),
                    model_id=str(self._config.get("model", "")),
                    finish_reason=str(getattr(raw, "done_reason", "")),
                    usage=getattr(raw, "usage", {}),
                ) from initial_error
            repaired = True
            try:
                repaired_raw = self._complete(
                    call_config,
                    repair_messages := self._repair_messages(
                        request,
                        raw,
                        include_schema=(
                            not native_ollama
                            and structured_output_mode in {"json_object", "json", "none"}
                        ),
                    ),
                    max_tokens=_fit_context_window(
                        self._config,
                        repair_messages,
                        self._repair_budget(max_tokens, raw),
                        extra_tokens=transport_extra_tokens,
                        safety_margin=transport_safety_margin,
                    ),
                )
                self._ensure_complete(repaired_raw)
                payload = self._parse_and_validate(
                    repaired_raw,
                    request.response_schema,
                    normalize_vertical=request.lens_id.startswith("vertical."),
                )
                return payload, repaired, repaired_raw
            except _InvalidStructuredResponse as exc:
                raise StructuredOutputFailure(
                    f"{_REPAIR_FAILURE}: {exc}",
                    code=exc.code,
                    raw_response=str(repaired_raw or ""),
                    initial_raw_response=str(raw or ""),
                    schema_hash=canonical_hash(request.response_schema),
                    retry_count=1,
                    provider_id=str(self._config.get("id", self._config.get("label", "openai-compatible"))),
                    model_id=str(self._config.get("model", "")),
                    finish_reason=str(getattr(repaired_raw, "done_reason", "")),
                    usage=getattr(repaired_raw, "usage", {}),
                ) from exc
            except TransportFailure as exc:
                raise TransportFailure(
                    str(exc),
                    code=exc.code,
                    provider_id=exc.provider_id or str(self._config.get("id", self._config.get("label", "openai-compatible"))),
                    model_id=exc.model_id or str(self._config.get("model", "")),
                    raw_response=str(raw or ""),
                    initial_raw_response=str(raw or ""),
                    schema_hash=canonical_hash(request.response_schema),
                    retry_count=1,
                ) from exc
            except Exception as exc:
                if isinstance(exc, AdapterFailure):
                    raise
                raise TransportFailure(
                    _REPAIR_FAILURE,
                    provider_id=str(self._config.get("id", self._config.get("label", "openai-compatible"))),
                    model_id=str(self._config.get("model", "")),
                    code="structural_retry_transport",
                    raw_response=str(raw or ""),
                    initial_raw_response=str(raw or ""),
                    schema_hash=canonical_hash(request.response_schema),
                    retry_count=1,
                ) from exc


    def complete_json(self, request: GenerationRequest) -> GenerationResponse:
        started = time.monotonic()
        max_tokens = _bounded_max_tokens(self._config, request.max_tokens)
        native_ollama = _is_native_ollama(self._config)
        structured_output_mode = str(
            self._config.get("structured_output_mode", "json_schema")
        ).casefold()
        prompt_payload: dict[str, object] = {"input": request.user_payload}
        if not native_ollama and structured_output_mode in {
            "json_object",
            "json",
            "none",
        }:
            # A json_schema response format already delivers the schema to an
            # OpenAI-compatible provider. Repeating it in the user message
            # wastes context tokens and can push a long vertical request over
            # the provider's actual context window. Modes without schema
            # enforcement still need the prompt copy as model guidance.
            prompt_payload["response_schema"] = request.response_schema
        messages = [
            {
                "role": "system",
                "content": add_simplified_chinese_instruction(request.system_prompt),
            },
            {
                "role": "user",
                "content": json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True),
            },
        ]
        call_config, transport_extra_tokens, transport_safety_margin = _provider_call_config(
            self._config,
            request,
            native_ollama=native_ollama,
            structured_output_mode=structured_output_mode,
        )
        max_tokens = _fit_context_window(
            self._config,
            messages,
            max_tokens,
            extra_tokens=transport_extra_tokens,
            safety_margin=transport_safety_margin,
        )
        try:
            raw = self._complete(call_config, messages, max_tokens=max_tokens)
        except Exception as exc:
            if isinstance(exc, AdapterFailure):
                raise
            raise TransportFailure(
                "LLM completion failed",
                code="completion_failed",
                provider_id=str(self._config.get("id", self._config.get("provider", ""))),
                model_id=str(self._config.get("model", "")),
            ) from exc
        payload, repaired, final_raw = self._validate_or_repair(
            request,
            raw,
            call_config,
            max_tokens,
            native_ollama=native_ollama,
            structured_output_mode=structured_output_mode,
            transport_extra_tokens=transport_extra_tokens,
            transport_safety_margin=transport_safety_margin,
        )
        return GenerationResponse(
            lens_id=request.lens_id,
            payload=payload,
            input_hash=canonical_hash((request.lens_id, request.user_payload, request.response_schema)),
            output_hash=canonical_hash(payload),
            repaired=repaired,
            provider_id=str(self._config.get("id", self._config.get("label", "openai-compatible"))),
            model_id=str(self._config.get("model", "")),
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            status="completed",
            finish_reason=str(getattr(final_raw, "done_reason", "")),
            usage=getattr(final_raw, "usage", {}),
        )
