import json

import pytest

from rflp_lite.adapters.openai_compatible_model import OpenAICompatibleModel
from rflp_lite.adapters.llm_client import _fit_context_window
from rflp_lite.domain.errors import AdapterFailure, StructuredOutputFailure, TransportFailure
from rflp_lite.methodology.tasks import output_contract
from rflp_lite.methodology.vertical_generation import stage_task
from rflp_lite.ports.generative_model import (
    GenerationRequest,
    SIMPLIFIED_CHINESE_OUTPUT_INSTRUCTION,
)


def request() -> GenerationRequest:
    return GenerationRequest(
        lens_id="stakeholders",
        system_prompt="只返回 JSON",
        user_payload={"mission": "城市医疗运输"},
        response_schema={
            "type": "object",
            "required": ["items"],
            "properties": {"items": {"type": "array"}},
        },
        max_tokens=1200,
    )


def long_request() -> GenerationRequest:
    result = request()
    return GenerationRequest(
        lens_id=result.lens_id,
        system_prompt=result.system_prompt,
        user_payload=result.user_payload,
        response_schema={
            "type": "object",
            "required": ["items"],
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 2000},
                }
            },
        },
        max_tokens=result.max_tokens,
    )


def test_openai_compatible_model_enables_requirement_batching():
    assert OpenAICompatibleModel({"model": "remote"}).supports_requirement_batching is True
    assert OpenAICompatibleModel({"model": "remote"}).supports_parallel_requirement_batching is True
    assert OpenAICompatibleModel({"model": "remote", "model_location": "remote"}).supports_vv_case_splitting is True


def test_openai_compatible_remote_model_uses_mixed_r_backbone_by_default():
    remote = OpenAICompatibleModel({
        "model": "remote",
        "model_location": "remote",
    })
    compatibility = OpenAICompatibleModel({
        "model": "remote",
        "model_location": "remote",
        "r_backbone_single_kind": True,
    })
    local = OpenAICompatibleModel({
        "model": "local",
        "model_location": "local",
    })
    opted_in = OpenAICompatibleModel({
        "model": "remote",
        "model_location": "remote",
        "vertical_feedback": True,
    })
    first_pass = OpenAICompatibleModel({
        "model": "remote",
        "model_location": "remote",
        "automatic_operational_completion": False,
        "vertical_vv_case_splitting": False,
    })

    assert remote.r_backbone_single_kind is False
    assert remote.supports_parallel_r_backbone is True
    assert compatibility.r_backbone_single_kind is True
    assert compatibility.supports_parallel_r_backbone is True
    assert local.r_backbone_single_kind is False
    assert local.supports_parallel_r_backbone is False
    assert remote.automatic_vertical_stage_feedback is False
    assert remote.automatic_vertical_stage_completion_bridge is False
    assert remote.automatic_operational_completion is True
    assert first_pass.automatic_operational_completion is False
    assert remote.supports_vv_case_splitting is True
    assert first_pass.supports_vv_case_splitting is False
    assert remote.vertical_batch_size == 2
    assert remote.vertical_functional_batch_size == 2
    assert remote.vertical_logical_batch_size == 1
    assert remote.vertical_physical_batch_size == 1
    assert remote.vertical_vv_batch_size == 1
    assert remote.vertical_batch_output_token_budget == 3072
    assert local.automatic_vertical_stage_feedback is True
    assert local.automatic_vertical_stage_completion_bridge is True
    assert local.automatic_operational_completion is False
    assert local.vertical_batch_size == 2
    assert local.vertical_functional_batch_size == 1
    assert local.vertical_logical_batch_size == 1
    assert local.vertical_physical_batch_size == 1
    assert local.supports_vv_case_splitting is False
    assert local.vertical_vv_batch_size == 2
    assert local.vertical_batch_output_token_budget == 3072
    assert opted_in.automatic_vertical_stage_feedback is True


def test_openai_compatible_model_can_disable_deterministic_completion_bridge():
    model = OpenAICompatibleModel({
        "model": "remote",
        "model_location": "remote",
        "vertical_completion_bridge": False,
    })

    assert model.automatic_vertical_stage_completion_bridge is False


def test_vertical_structural_repair_includes_typed_gap_and_validation_issue():
    calls = []

    def complete(_config, messages, *, max_tokens=None):
        calls.append(messages)
        if len(calls) == 1:
            return '{"entities":[{"local_ref":"function-1","kind":"function","name":"功能","payload":{}}]}'
        return '{"entities":[],"relations":[],"updates":[],"deprecations":[],"reason":"修复"}'

    model = OpenAICompatibleModel({"model": "remote"}, complete=complete)
    request_value = GenerationRequest(
        lens_id="vertical.functional",
        system_prompt="只返回 JSON",
        user_payload={"max_items": 2},
        response_schema={
            "type": "object",
            "required": ["entities", "relations", "updates", "deprecations", "reason"],
            "properties": {
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["kind", "payload"],
                        "properties": {
                            "local_ref": {"type": "string"},
                            "kind": {"const": "function"},
                            "name": {"type": "string"},
                            "payload": {
                                "type": "object",
                                "required": ["decomposition"],
                            },
                        },
                    },
                },
                "relations": {"type": "array"},
                "updates": {"type": "array"},
                "deprecations": {"type": "array"},
                "reason": {"type": "string"},
            },
        },
        max_tokens=1200,
    )

    model.complete_json(request_value)

    repair_system = calls[-1][0]["content"]
    assert "source_function_ids" in repair_system
    assert "具体问题修复" in repair_system


def test_openai_compatible_model_exposes_bounded_parallelism():
    remote = OpenAICompatibleModel({
        "model": "remote",
        "model_location": "remote",
    })
    local = OpenAICompatibleModel({
        "model": "local",
        "model_location": "local",
    })
    explicit = OpenAICompatibleModel({
        "model": "remote",
        "model_location": "remote",
        "max_parallel_requests": 1,
    })

    assert remote.max_parallel_requests == 2
    assert local.max_parallel_requests == 4
    assert explicit.max_parallel_requests == 1


def test_adapter_parses_json_and_records_hashes():
    calls = []

    def complete(config, messages, *, max_tokens=None):
        calls.append((config, messages, max_tokens))
        return '{"items":[]}'

    result = OpenAICompatibleModel({"model": "local"}, complete=complete).complete_json(request())
    assert result.payload == {"items": []}
    assert result.input_hash and result.output_hash
    assert result.model_id == "local"
    assert result.provider_id == "openai-compatible"
    assert result.duration_ms >= 0
    assert result.status == "completed"
    assert result.repaired is False
    assert calls[0][2] == 1200


def test_adapter_telemetry_counts_structural_repair_transport_attempt():
    calls = []
    events = []

    def complete(_config, _messages, *, max_tokens=None):
        calls.append(max_tokens)
        return "not-json" if len(calls) == 1 else '{"items": []}'

    model = OpenAICompatibleModel(
        {"model": "local"},
        complete=complete,
        telemetry_sink=events.append,
    )

    result = model.complete_json(request())

    assert result.payload == {"items": []}
    assert [event.attempt_kind for event in events] == ["initial", "structural_repair"]
    assert all(event.status == "completed" for event in events)
    assert len(calls) == 2


def test_budget_matched_adapter_stops_after_measured_output_cap():
    calls = []

    class Response(str):
        usage = {"output_tokens": 5}

    def complete(_config, _messages, *, max_tokens=None):
        calls.append(max_tokens)
        return Response('{"items": []}')

    model = OpenAICompatibleModel(
        {"model": "local", "benchmark_total_output_token_budget": 5},
        complete=complete,
    )

    assert model.complete_json(request()).payload == {"items": []}
    with pytest.raises(AdapterFailure, match="budget exhausted"):
        model.complete_json(request())
    assert calls == [5]


def test_budget_matched_adapter_fails_closed_without_output_usage():
    class Response(str):
        usage = {"total_tokens": 5}

    model = OpenAICompatibleModel(
        {"model": "local", "benchmark_total_output_token_budget": 5},
        complete=lambda *_args, **_kwargs: Response('{"items": []}'),
    )

    with pytest.raises(AdapterFailure, match="output token usage unavailable"):
        model.complete_json(request())


def test_adapter_fits_output_to_configured_context_window():
    calls = []

    def complete(_config, _messages, *, max_tokens=None):
        calls.append(max_tokens)
        return '{"items": []}'

    model = OpenAICompatibleModel(
        {
            "provider": "ollama",
            "kind": "local",
            "context_window": 2048,
            "model": "qwen",
        },
        complete=complete,
    )
    model.complete_json(
        GenerationRequest(
            lens_id="stakeholders",
            system_prompt="只返回 JSON",
                user_payload={"mission": "城市医疗运输" * 140},
            response_schema=request().response_schema,
            max_tokens=1200,
        )
    )

    assert 0 < calls[0] < 1200


def test_adapter_rejects_prompt_when_context_window_cannot_fit_output():
    model = OpenAICompatibleModel(
        {
            "provider": "ollama",
            "kind": "local",
            "context_window": 512,
            "model": "qwen",
        },
        complete=lambda *_args, **_kwargs: '{"items": []}',
    )

    with pytest.raises(TransportFailure, match="context window") as error:
        model.complete_json(
            GenerationRequest(
                lens_id="stakeholders",
                system_prompt="只返回 JSON",
                user_payload={"mission": "城市医疗运输" * 300},
                response_schema=request().response_schema,
                max_tokens=1200,
            )
        )

    assert error.value.code == "context_window_exceeded"


def test_context_window_margin_covers_provider_tokenizer_boundary():
    messages = [{"role": "user", "content": "中" * 12220}]

    # The model-independent estimate is exactly at the old 64-token boundary;
    # a provider counting 65 additional wrapper/punctuation tokens would
    # reject the resulting 4096-token request against a 16384-token window.
    assert _fit_context_window(
        {"context_window": 16384}, messages, 4096
    ) == 3904


def test_fit_context_window_accounts_for_transport_tokens_and_custom_margin():
    messages = [{"role": "user", "content": "中" * 1000}]

    assert _fit_context_window(
        {"context_window": 4096},
        messages,
        3000,
        extra_tokens=500,
        safety_margin=512,
    ) == 2080


def test_openai_compatible_model_reserves_response_format_context():
    calls = []

    def complete(_config, _messages, *, max_tokens=None):
        calls.append(max_tokens)
        return '{"items": []}'

    model = OpenAICompatibleModel(
        {
            "kind": "local",
            "provider": "openai-compatible",
            "base_url": "http://127.0.0.1:18000/v1",
            "model": "qwen3.5-controller",
            "context_window": 8192,
        },
        complete=complete,
    )
    model.complete_json(
        GenerationRequest(
            lens_id="stakeholders",
            system_prompt="只返回 JSON",
            user_payload={"mission": "城市医疗运输" * 50},
            response_schema={
                "type": "object",
                "required": ["items"],
                "properties": {"items": {"type": "array"}},
            },
            max_tokens=5000,
        )
    )

    assert 256 <= calls[0] < 5000


def test_requirements_schema_accepts_operational_scenario_description():
    schema = output_contract(stage_task("requirements"))
    payload = {
        "entities": [{
            "local_ref": "operational-scenario",
            "kind": "operational_scenario",
            "name": "正常巡检作业",
            "payload": {"description": "按预定航线执行巡检并上传结果"},
        }],
        "relations": [],
        "updates": [],
        "deprecations": [],
        "reason": "补齐运行场景",
    }

    OpenAICompatibleModel._parse_and_validate(json.dumps(payload, ensure_ascii=False), schema)


def test_physical_schema_coerces_structured_scalar_measurements():
    schema = output_contract(stage_task("physical"))
    payload = {
        "entities": [{
            "local_ref": "physical-1",
            "kind": "physical_block",
            "name": "续航控制器",
            "payload": {
                "candidate_type": "embedded_controller",
                "selection_rationale": "满足当前逻辑职责",
                "compute": {"cpu_mhz": 168, "cores": 1, "fpu": True},
                "thermal": {"dissipation_w": 2.5, "cooling": "passive"},
            },
        }],
        "relations": [],
        "updates": [],
        "deprecations": [],
        "reason": "选择物理候选",
    }

    normalized = OpenAICompatibleModel._parse_and_validate(
        json.dumps(payload, ensure_ascii=False), schema, normalize_vertical=True
    )

    physical_payload = normalized["entities"][0]["payload"]
    assert isinstance(physical_payload["compute"], str)
    assert isinstance(physical_payload["thermal"], str)


def test_requirements_repair_keeps_context_without_redundant_guidance():
    repair_request = GenerationRequest(
        lens_id="vertical.requirements",
        system_prompt="只返回 TaskProposal",
        user_payload={
            "context": {"entities": []},
            "requirement_worklist": [],
            "methodology_guidance": {"findings": ["重复信息"]},
        },
        response_schema={"type": "object"},
    )

    messages = OpenAICompatibleModel._repair_messages(repair_request, "失效响应")
    envelope = json.loads(messages[1]["content"])

    assert set(envelope["input"]) == {"context", "requirement_worklist"}
    assert "最多返回 32 项" in messages[0]["content"]


def test_vertical_repair_preserves_requirement_batch_scope():
    repair_request = GenerationRequest(
        lens_id="vertical.functional",
        system_prompt="只返回 TaskProposal",
        user_payload={
            "context": {"entities": []},
            "requirement_worklist": [{"requirement_id": "req-1"}],
            "requirement_batch": {"index": 2, "count": 3, "is_first": False},
        },
        response_schema={"type": "object"},
    )

    messages = OpenAICompatibleModel._repair_messages(repair_request, "失效响应")
    envelope = json.loads(messages[1]["content"])

    assert envelope["input"]["requirement_batch"] == {
        "count": 3,
        "index": 2,
        "is_first": False,
    }
    assert "第 2/3 个需求批次" in messages[0]["content"]


def test_r_repair_preserves_narrow_slice_scope():
    repair_request = GenerationRequest(
        lens_id="vertical.requirements",
        system_prompt="只返回 TaskProposal",
        user_payload={
            "context": {"entities": []},
            "requirement_worklist": [],
            "r_slice": {
                "slice_kind": "r_backbone_behavior",
                "allowed_kinds": ["use_case", "activity"],
                "slice_index": 2,
                "slice_count": 4,
            },
        },
        response_schema={"type": "object"},
    )

    messages = OpenAICompatibleModel._repair_messages(repair_request, "失效响应")
    envelope = json.loads(messages[1]["content"])

    assert envelope["input"]["r_slice"] == {
        "slice_count": 4,
        "slice_index": 2,
        "slice_kind": "r_backbone_behavior",
        "allowed_kinds": ["use_case", "activity"],
    }


def test_wide_vertical_batch_routes_structural_failure_to_runtime_split():
    calls = []
    wide_request = GenerationRequest(
        lens_id="vertical.functional",
        system_prompt="只返回 TaskProposal",
        user_payload={
            "context": {"entities": []},
            "requirement_worklist": [
                {"requirement_id": "req-1"},
                {"requirement_id": "req-2"},
            ],
            "requirement_batch": {"index": 1, "count": 1, "is_first": True},
        },
        response_schema={"type": "object"},
    )

    def complete(*_args, **_kwargs):
        calls.append(True)
        return "not-json"

    with pytest.raises(StructuredOutputFailure) as error:
        OpenAICompatibleModel(
            {"kind": "local", "model": "qwen"}, complete=complete
        ).complete_json(wide_request)

    assert len(calls) == 1
    assert error.value.retry_count == 0


def test_vertical_payload_normalizes_wire_relations_before_schema_validation():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["entities", "relations", "updates", "deprecations", "reason"],
        "properties": {
            "entities": {"type": "array", "items": {"type": "object"}},
            "relations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["source_ref", "predicate", "target_ref", "evidence_ids"],
                    "properties": {
                        "source_ref": {"type": "string"},
                        "predicate": {"enum": ["derivedFrom"]},
                        "target_ref": {"type": "string"},
                        "evidence_ids": {"type": "array"},
                    },
                },
            },
            "updates": {"type": "array"},
            "deprecations": {"type": "array"},
            "reason": {"type": "string"},
        },
    }
    payload = OpenAICompatibleModel._parse_and_validate(
        json.dumps({
            "entities": [],
            "relations": [
                {"source_ref": "r-1", "predicate": "derivedFrom", "target_ref": "c-1"},
                {"source_ref": "r-1", "predicate": "participatesI", "target_ref": "s-1"},
            ],
            "updates": [],
            "deprecations": [],
            "reason": "保留有效关系",
            "ignored": True,
        }),
        schema,
        normalize_vertical=True,
    )

    assert payload["relations"] == [{
        "source_ref": "r-1",
        "predicate": "derivedFrom",
        "target_ref": "c-1",
        "evidence_ids": [],
    }]
    assert "ignored" not in payload


def test_vertical_payload_normalizes_minimal_system_wire_payload():
    schema = output_contract(stage_task("requirements"))
    payload = {
        "entities": [{
            "local_ref": "system-1",
            "kind": "system",
            "name": "人工接管系统",
            "payload": {"description": "支持人工安全接管"},
        }],
        "relations": [],
        "updates": [],
        "deprecations": [],
        "reason": "建立系统边界",
    }

    normalized = OpenAICompatibleModel._parse_and_validate(
        json.dumps(payload, ensure_ascii=False),
        schema,
        normalize_vertical=True,
    )

    system_payload = normalized["entities"][0]["payload"]
    assert system_payload["mission"] == "支持人工安全接管"
    assert system_payload["system_boundary"] == {"inside": [], "outside": []}
    assert system_payload["open_questions"] == []


def test_vertical_payload_normalizes_structured_logical_reasoning():
    schema = output_contract(stage_task("logical"))
    payload = {
        "entities": [{
            "local_ref": "logical-1",
            "kind": "logical_component",
            "name": "安全接管逻辑单元",
            "payload": {
                "responsibility": "执行安全接管",
                "partition_basis": {"function_ids": ["function-1"]},
                "shared_state": [{"id": "state-1", "name": "接管中"}],
                "safety_isolation": {"level": "high"},
                "alternative_partitions": [{"name": "shared_coordinator", "score": 82}],
                "architecture_rationale": {"basis": "控制权转移需要隔离"},
            },
        }],
        "relations": [],
        "updates": [],
        "deprecations": [],
        "reason": "建立逻辑架构",
    }

    normalized = OpenAICompatibleModel._parse_and_validate(
        json.dumps(payload, ensure_ascii=False),
        schema,
        normalize_vertical=True,
    )

    logical_payload = normalized["entities"][0]["payload"]
    assert logical_payload["partition_basis"] == '{"function_ids": ["function-1"]}'
    assert logical_payload["architecture_rationale"] == "控制权转移需要隔离"
    assert logical_payload["shared_state"] == ["接管中"]
    assert logical_payload["shared_state_ids"] == ["state-1"]
    assert logical_payload["safety_isolation"] == [{"level": "high"}]
    assert logical_payload["alternative_partitions"] == [
        '{"name": "shared_coordinator", "score": 82}'
    ]
    assert logical_payload["architecture_reasoning"] == {"basis": "控制权转移需要隔离"}


def test_vertical_payload_maps_physical_feasibility_status() -> None:
    schema = output_contract(stage_task("physical"))
    payload = {
        "entities": [{
            "local_ref": "physical-1",
            "kind": "physical_block",
            "name": "返航执行单元",
            "payload": {
                "candidate_type": "controller",
                "feasibility": "feasible",
            },
        }],
        "relations": [],
        "updates": [],
        "deprecations": [],
        "reason": "选择物理候选",
    }

    normalized = OpenAICompatibleModel._parse_and_validate(
        json.dumps(payload, ensure_ascii=False),
        schema,
        normalize_vertical=True,
    )

    assert normalized["entities"][0]["payload"]["feasibility"] == {
        "status": "feasible"
    }


def test_vertical_payload_maps_partition_basis_to_logical_rationale() -> None:
    schema = output_contract(stage_task("logical"))
    payload = {
        "entities": [{
            "local_ref": "logical-1",
            "kind": "logical_component",
            "name": "安全接管逻辑单元",
            "payload": {
                "responsibility": "执行安全接管",
                "partition_basis": {"function_ids": ["function-1"]},
            },
        }],
        "relations": [],
        "updates": [],
        "deprecations": [],
        "reason": "建立逻辑架构",
    }

    normalized = OpenAICompatibleModel._parse_and_validate(
        json.dumps(payload, ensure_ascii=False),
        schema,
        normalize_vertical=True,
    )

    logical_payload = normalized["entities"][0]["payload"]
    assert logical_payload["architecture_rationale"] == (
        '{"function_ids": ["function-1"]}'
    )


def test_vertical_payload_maps_function_purpose_to_required_decomposition():
    schema = output_contract(stage_task("functional"))
    payload = {
        "entities": [{
            "local_ref": "function-1",
            "kind": "function",
            "name": "执行安全接管",
            "payload": {"purpose": "在异常情况下完成安全接管"},
        }],
        "relations": [],
        "updates": [],
        "deprecations": [],
        "reason": "识别功能",
    }

    normalized = OpenAICompatibleModel._parse_and_validate(
        json.dumps(payload, ensure_ascii=False),
        schema,
        normalize_vertical=True,
    )

    assert normalized["entities"][0]["payload"]["decomposition"] == (
        "在异常情况下完成安全接管"
    )


def test_vertical_payload_infers_functional_references_from_provider_relations():
    schema = output_contract(stage_task("functional"))
    payload = {
        "entities": [
            {
                "local_ref": "function-1",
                "kind": "function",
                "name": "采集数据",
                "payload": {"purpose": "采集数据"},
            },
            {
                "local_ref": "function-2",
                "kind": "function",
                "name": "处理数据",
                "payload": {"purpose": "处理数据"},
            },
            {
                "local_ref": "flow-1",
                "kind": "functional_flow",
                "name": "数据流",
                "payload": {"description": "采集结果传递给处理功能"},
            },
            {
                "local_ref": "scenario-1",
                "kind": "functional_scenario",
                "name": "处理场景",
                "payload": {"description": "完整处理场景"},
            },
        ],
        "relations": [
            {
                "source_ref": "function-1",
                "predicate": "exchangesWith",
                "target_ref": "flow-1",
                "evidence_ids": [],
            },
            {
                "source_ref": "flow-1",
                "predicate": "exchangesWith",
                "target_ref": "function-2",
                "evidence_ids": [],
            },
            {
                "source_ref": "function-1",
                "predicate": "derivedFrom",
                "target_ref": "scenario-1",
                "evidence_ids": [],
            },
        ],
        "updates": [],
        "deprecations": [],
        "reason": "建立功能链",
    }

    normalized = OpenAICompatibleModel._parse_and_validate(
        json.dumps(payload, ensure_ascii=False),
        schema,
        normalize_vertical=True,
    )

    by_ref = {item["local_ref"]: item["payload"] for item in normalized["entities"]}
    assert by_ref["flow-1"]["source_function_ids"] == ["function-1"]
    assert by_ref["flow-1"]["target_function_ids"] == ["function-2"]
    assert by_ref["scenario-1"]["function_ids"] == ["function-1"]


def test_vertical_payload_infers_references_to_existing_canonical_function():
    payload = {
        "entities": [
            {
                "local_ref": "flow-1",
                "kind": "functional_flow",
                "name": "已有功能输出流",
                "payload": {"description": "输出"},
            },
            {
                "local_ref": "scenario-1",
                "kind": "functional_scenario",
                "name": "已有功能场景",
                "payload": {"description": "场景"},
            },
        ],
        "relations": [
            {
                "source_ref": "function-existing",
                "predicate": "exchangesWith",
                "target_ref": "flow-1",
            },
            {
                "source_ref": "flow-1",
                "predicate": "exchangesWith",
                "target_ref": "function-existing",
            },
            {
                "source_ref": "function-existing",
                "predicate": "derivedFrom",
                "target_ref": "scenario-1",
            },
        ],
    }

    normalized = OpenAICompatibleModel._parse_and_validate(
        json.dumps(payload, ensure_ascii=False),
        output_contract(stage_task("functional")),
        normalize_vertical=True,
    )
    by_ref = {item["local_ref"]: item["payload"] for item in normalized["entities"]}

    assert by_ref["flow-1"]["source_function_ids"] == ["function-existing"]
    assert by_ref["scenario-1"]["function_ids"] == ["function-existing"]


def test_vertical_payload_normalizes_physical_constraint_shape_and_rationale():
    schema = output_contract(stage_task("physical"))
    payload = {
        "entities": [{
            "local_ref": "physical-1",
            "kind": "physical_block",
            "name": "安全接管执行单元",
            "payload": {
                "candidate_type": "solution_class",
            "rationale": "承载接管控制职责",
            "propagated_constraints": [{"name": "实时响应"}],
            "alternatives": [{"option": "shared_safety_bus", "task": "评估复用"}],
        },
        }],
        "relations": [],
        "updates": [],
        "deprecations": [],
        "reason": "选择物理候选",
    }

    normalized = OpenAICompatibleModel._parse_and_validate(
        json.dumps(payload, ensure_ascii=False),
        schema,
        normalize_vertical=True,
    )

    physical_payload = normalized["entities"][0]["payload"]
    assert physical_payload["selection_rationale"] == "承载接管控制职责"
    assert physical_payload["propagated_constraints"] == {
        "items": [{"name": "实时响应"}],
    }
    assert physical_payload["alternatives"] == ["shared_safety_bus"]


def test_vertical_payload_normalizes_vv_procedure_steps_to_executable_text():
    schema = output_contract(stage_task("verification_validation"))
    payload = {
        "entities": [{
            "local_ref": "validation-1",
            "kind": "validation_case",
            "name": "场景确认用例",
            "payload": {
                "method": "演示",
                "verification_objective": "确认场景目标达成",
                "precondition": "系统处于待命状态",
                "test_condition": "高保真模拟场景",
                "input": "模拟事件流",
                "stimulus": "触发安全事件",
                "procedure": ["触发事件", "执行接管", "记录结果"],
                "expected_result": "接管成功",
                "pass_criteria": "总耗时满足需求",
            },
        }],
        "relations": [],
        "updates": [],
        "deprecations": [],
        "reason": "建立验证计划",
    }

    normalized = OpenAICompatibleModel._parse_and_validate(
        json.dumps(payload, ensure_ascii=False),
        schema,
        normalize_vertical=True,
    )

    assert normalized["entities"][0]["payload"]["procedure"] == "触发事件；执行接管；记录结果"


def test_vertical_payload_recovers_complete_prefix_without_provider_repair():
    class TruncatedText(str):
        done_reason = "length"

    schema = output_contract(stage_task("requirements"))
    raw = TruncatedText(
        '{"entities":[{"local_ref":"system-1","kind":"system",'
        '"name":"人工接管系统","payload":{"description":"支持人工安全接管"}}]'
    )
    calls = []

    result = OpenAICompatibleModel(
        {"model": "qwen", "local_max_tokens": 1000},
        complete=lambda *_args, **_kwargs: (calls.append(True) or raw),
    ).complete_json(GenerationRequest(
        lens_id="vertical.requirements",
        system_prompt="只返回 TaskProposal",
        user_payload={},
        response_schema=schema,
        max_tokens=800,
    ))

    assert calls == [True]
    assert result.repaired is True
    assert result.payload["entities"][0]["payload"]["mission"] == "支持人工安全接管"


def test_adapter_preserves_finish_reason_and_usage():
    class CompletedText(str):
        done_reason = "stop"
        usage = {"prompt_tokens": 4, "completion_tokens": 3}

    result = OpenAICompatibleModel(
        {"model": "local"},
        complete=lambda *_args, **_kwargs: CompletedText('{"items": []}'),
    ).complete_json(request())

    assert result.finish_reason == "stop"
    assert result.usage == {"prompt_tokens": 4, "completion_tokens": 3}


def test_adapter_reports_final_finish_reason_and_usage_after_repair():
    class InitialText(str):
        done_reason = "length"
        usage = {"completion_tokens": 1200}

    class RepairedText(str):
        done_reason = "stop"
        usage = {"completion_tokens": 5}

    answers = iter((InitialText('{"items": ['), RepairedText('{"items": []}')))
    result = OpenAICompatibleModel(
        {"kind": "local", "model": "qwen"},
        complete=lambda *_args, **_kwargs: next(answers),
    ).complete_json(request())

    assert result.repaired is True
    assert result.finish_reason == "stop"
    assert result.usage == {"completion_tokens": 5}


def test_adapter_adds_simplified_chinese_instruction_to_initial_prompt():
    calls = []

    def complete(_config, messages, *, max_tokens=None):
        calls.append(messages)
        return '{"items":[]}'

    OpenAICompatibleModel({"model": "local"}, complete=complete).complete_json(request())

    assert SIMPLIFIED_CHINESE_OUTPUT_INSTRUCTION in calls[0][0]["content"]
    assert "只返回 JSON" in calls[0][0]["content"]


def test_adapter_adds_simplified_chinese_instruction_to_repair_prompt():
    calls = []
    answers = iter(("not-json", '{"items":[]}'))

    def complete(_config, messages, *, max_tokens=None):
        calls.append(messages)
        return next(answers)

    OpenAICompatibleModel({"model": "local"}, complete=complete).complete_json(request())

    assert SIMPLIFIED_CHINESE_OUTPUT_INSTRUCTION in calls[1][0]["content"]
    assert "重新生成完整的 JSON 分析结果" in calls[1][0]["content"]


def test_adapter_repairs_invalid_json_once():
    answers = iter(("not-json", '{"items":[]}'))
    model = OpenAICompatibleModel(
        {"model": "local"}, complete=lambda *_args, **_kwargs: next(answers)
    )
    result = model.complete_json(request())
    assert result.payload == {"items": []}
    assert result.repaired is True


def test_adapter_repairs_provider_length_stop_with_full_budget():
    class TruncatedText(str):
        done_reason = "length"

    answers = iter((TruncatedText('{"items": ['), '{"items":[]}'))
    calls = []

    def complete(_config, _messages, *, max_tokens=None):
        calls.append(max_tokens)
        return next(answers)

    result = OpenAICompatibleModel(
        {"kind": "local", "model": "qwen", "local_max_tokens": 3000},
        complete=complete,
    ).complete_json(request())

    assert result.repaired is True
    assert calls == [1200, 2400]


def test_adapter_passes_request_schema_to_openai_compatible_completion():
    captured = {}

    def complete(config, messages, *, max_tokens=None):
        captured["config"] = config
        return '{"items":[]}'

    model = OpenAICompatibleModel(
        {
            "kind": "local",
            "provider": "openai-compatible",
            "base_url": "http://127.0.0.1:18000/v1",
            "model": "qwen3.5-controller",
        },
        complete=complete,
    )
    model.complete_json(request())

    assert captured["config"]["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "stakeholders",
            "strict": True,
            "schema": request().response_schema,
        },
    }


def test_ollama_receives_task_proposal_schema_as_format():
    captured = {}
    proposal = GenerationRequest(
        lens_id="task",
        system_prompt="只返回 TaskProposal",
        user_payload={},
        response_schema={
            "type": "object",
            "required": ["entities", "relations", "updates", "deprecations", "reason"],
            "properties": {
                "entities": {"type": "array"},
                "relations": {"type": "array"},
                "updates": {"type": "array"},
                "deprecations": {"type": "array"},
                "reason": {"type": "string"},
            },
        },
    )

    def complete(config, _messages, *, max_tokens=None):
        captured["config"] = config
        return '{"entities": [], "relations": [], "updates": [], "deprecations": [], "reason": "无变化"}'

    OpenAICompatibleModel(
        {"kind": "local", "provider": "ollama", "model": "qwen3.5:9b-q8_0"},
        complete=complete,
    ).complete_json(proposal)

    assert captured["config"]["json_schema"]["required"] == proposal.response_schema["required"]


def test_structured_output_mode_none_disables_native_provider_constraint():
    captured = {}

    def complete(config, _messages, *, max_tokens=None):
        captured["config"] = config
        return '{"items": []}'

    OpenAICompatibleModel(
        {
            "kind": "local",
            "provider": "ollama",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen3.5:9b",
            "structured_output_mode": "none",
        },
        complete=complete,
    ).complete_json(request())

    assert "json_schema" not in captured["config"]


def test_openai_compatible_receives_structured_response_format():
    captured = {}
    proposal = request()

    def complete(config, _messages, *, max_tokens=None):
        captured["config"] = config
        return '{"items": []}'

    OpenAICompatibleModel(
        {"model": "remote", "structured_output_mode": "json_schema"},
        complete=complete,
    ).complete_json(proposal)

    assert captured["config"]["response_format"]["type"] == "json_schema"
    assert captured["config"]["response_format"]["json_schema"]["schema"] == proposal.response_schema


def test_openai_json_schema_is_not_repeated_in_prompt():
    captured = {}

    def complete(config, messages, *, max_tokens=None):
        captured["config"] = config
        captured["messages"] = messages
        return '{"items": []}'

    OpenAICompatibleModel(
        {
            "provider": "openai-compatible",
            "model": "remote",
            "structured_output_mode": "json_schema",
        },
        complete=complete,
    ).complete_json(request())

    assert "response_schema" not in json.loads(captured["messages"][1]["content"])
    assert captured["config"]["response_format"]["type"] == "json_schema"


def test_openai_provider_schema_avoids_unsupported_one_of_but_keeps_common_shape():
    captured = {}
    proposal = request()
    proposal.response_schema["oneOf"] = [{"required": ["items"]}]
    proposal.response_schema["x-payload-schemas"] = {"requirement": {"type": "object"}}

    def complete(config, _messages, *, max_tokens=None):
        captured["config"] = config
        return '{"items": []}'

    OpenAICompatibleModel(
        {"provider": "openai-compatible", "model": "remote"},
        complete=complete,
    ).complete_json(proposal)

    provider_schema = captured["config"]["response_format"]["json_schema"]["schema"]
    assert "oneOf" not in provider_schema
    assert "x-payload-schemas" not in provider_schema
    assert provider_schema["required"] == proposal.response_schema["required"]


def test_openai_compatible_honors_json_object_output_mode():
    captured = {}

    def complete(config, _messages, *, max_tokens=None):
        captured["config"] = config
        return '{"items": []}'

    OpenAICompatibleModel(
        {
            "kind": "local",
            "provider": "openai-compatible",
            "base_url": "http://127.0.0.1:18000/v1",
            "model": "qwen3.5-controller",
            "structured_output_mode": "json_object",
        },
        complete=complete,
    ).complete_json(request())

    assert captured["config"]["response_format"] == {"type": "json_object"}


def test_ollama_transport_schema_removes_only_grammar_incompatible_length_limit():
    captured = {}

    def complete(config, messages, *, max_tokens=None):
        captured["config"] = config
        captured["messages"] = messages
        return '{"items":[]}'

    model = OpenAICompatibleModel(
        {
            "kind": "local",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen3.5:4b",
        },
        complete=complete,
    )
    model.complete_json(long_request())

    sent_schema = captured["config"]["json_schema"]
    assert sent_schema["properties"]["items"]["items"] == {"type": "string"}
    assert "response_schema" not in __import__("json").loads(
        captured["messages"][1]["content"]
    )


def test_ollama_structural_repair_does_not_duplicate_schema_in_prompt():
    calls = []
    answers = iter(("not-json", '{"items":[]}'))

    def complete(config, messages, *, max_tokens=None):
        calls.append((config, messages))
        return next(answers)

    model = OpenAICompatibleModel(
        {
            "kind": "local",
            "provider": "ollama",
            "base_url": "http://100.88.143.10:11434/v1",
            "model": "qwen3.5:9b-q8_0",
        },
        complete=complete,
    )
    model.complete_json(request())

    repair_payload = __import__("json").loads(calls[1][1][1]["content"])
    assert "response_schema" not in repair_payload


def test_adapter_parses_fenced_json_from_reasoning_fallback():
    model = OpenAICompatibleModel(
        {"model": "local"},
        complete=lambda *_args, **_kwargs: "分析完成：```json\n{\"items\": []}\n```",
    )

    result = model.complete_json(request())

    assert result.payload == {"items": []}


def test_adapter_fails_after_one_invalid_json_repair():
    model = OpenAICompatibleModel({"model": "local"}, complete=lambda *_args, **_kwargs: "not-json")
    with pytest.raises(AdapterFailure, match="JSON"):
        model.complete_json(request())


def test_invalid_structured_output_exposes_raw_response_and_one_retry():
    calls = []

    def complete(_config, _messages, *, max_tokens=None):
        calls.append(max_tokens)
        return "not-json" if len(calls) == 1 else "still-not-json"

    with pytest.raises(StructuredOutputFailure) as error:
        OpenAICompatibleModel({"kind": "local", "model": "qwen"}, complete=complete).complete_json(request())

    assert calls == [1200, 1200]
    assert error.value.stage == "structural"
    assert error.value.code == "json_decode"
    assert error.value.raw_response == "still-not-json"
    assert error.value.initial_raw_response == "not-json"
    assert error.value.retry_count == 1
    assert error.value.schema_hash


@pytest.mark.parametrize(
    "first_response",
    (
        "",
        '{"items": [',
        '{"items": "not-a-list"}',
    ),
)
def test_adapter_rejects_empty_truncated_and_schema_invalid_repair(first_response):
    calls = []

    def complete(_config, _messages, *, max_tokens=None):
        calls.append(max_tokens)
        return first_response

    model = OpenAICompatibleModel(
        {"kind": "local", "model": "qwen", "local_max_tokens": 900},
        complete=complete,
    )
    with pytest.raises(
        AdapterFailure, match="LLM response is not valid JSON after one repair"
    ):
        model.complete_json(request())

    assert calls == [900, 900]


def test_adapter_validates_repaired_json_against_schema():
    answers = iter(('{"items": "not-a-list"}', '{"items":[]}'))
    model = OpenAICompatibleModel(
        {"kind": "local", "model": "qwen"},
        complete=lambda *_args, **_kwargs: next(answers),
    )

    result = model.complete_json(request())

    assert result.payload == {"items": []}
    assert result.repaired is True


def test_adapter_wraps_repair_provider_failure_stably():
    calls = 0

    def complete(_config, _messages, *, max_tokens=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return "truncated"
        raise RuntimeError("provider disconnected")

    model = OpenAICompatibleModel(
        {"kind": "local", "model": "qwen"}, complete=complete
    )
    with pytest.raises(
        AdapterFailure, match="LLM response is not valid JSON after one repair"
    ):
        model.complete_json(request())

    assert calls == 2


def test_adapter_uses_smaller_request_budget_when_local_cap_is_larger():
    calls = []

    def complete(_config, _messages, *, max_tokens=None):
        calls.append(max_tokens)
        return '{"items":[]}'

    model = OpenAICompatibleModel(
        {"kind": "local", "model": "qwen", "local_max_tokens": 2400},
        complete=complete,
    )
    model.complete_json(request())

    assert calls == [1200]


def test_adapter_repair_keeps_full_block_budget_and_contains_only_block_envelope():
    calls = []
    answers = iter(("truncated", '{"items":[]}'))

    def complete(_config, messages, *, max_tokens=None):
        calls.append((messages, max_tokens))
        return next(answers)

    model = OpenAICompatibleModel(
        {
            "kind": "local",
            "model": "qwen",
            "local_max_tokens": 2400,
            "structured_output_mode": "json_object",
        },
        complete=complete,
    )
    model.complete_json(request())

    repair_messages, repair_budget = calls[1]
    assert repair_budget == 1200
    assert "重新生成完整的 JSON 分析结果" in repair_messages[0]["content"]
    assert "invalid_response" in repair_messages[1]["content"]
    assert "response_schema" in repair_messages[1]["content"]


def test_local_adapter_caps_large_output_requests():
    calls = []

    def complete(config, messages, *, max_tokens=None):
        calls.append(max_tokens)
        return '{"items":[]}'

    model = OpenAICompatibleModel(
        {"kind": "local", "model": "qwen", "local_max_tokens": 600},
        complete=complete,
    )
    model.complete_json(request())

    assert calls == [600]
