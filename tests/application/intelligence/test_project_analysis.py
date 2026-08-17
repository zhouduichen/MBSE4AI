from rflp_lite.application.intelligence.project_analysis import (
    apply_project_analysis,
    build_project_analysis_request,
)
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.ports.generative_model import GenerationResponse


def _state():
    return {
        "project_scope": {"workspace": "toothbrush", "input_hash": "input-1"},
        "document_regions": [{"id": "region-1", "text": "设计一款医用安全电动牙刷"}],
        "spans": [{"id": "span-1", "text": "设计一款医用安全电动牙刷"}],
        "claims": [],
        "stakeholders": [],
        "concerns": [],
        "needs": [],
        "structured_requirements": [],
        "scenarios": [],
        "discovery": {},
    }


def _payload():
    return {
        "system": {"name": "医用安全电动牙刷", "domain": "医疗器械", "mission": "安全清洁"},
        "stakeholders": [
            {"id": "s-user", "name": "患者", "category": "end_user", "goals": ["安全使用"]}
        ],
        "concerns": [
            {"id": "c-safety", "name": "口腔安全", "stakeholder_id": "s-user"}
        ],
        "needs": [
            {"id": "n-safe", "statement": "患者需要安全清洁", "stakeholder_id": "s-user", "concern_id": "c-safety"}
        ],
        "requirements": [
            {"id": "r-safe", "statement": "系统应限制刷牙压力", "subject": "系统", "predicate": "应", "source_type": "inferred"}
        ],
        "scenarios": [
            {"id": "sc-normal", "title": "正常刷牙", "scenario_type": "normal", "actors": ["患者"], "steps": ["启动", "刷牙"], "expected_outcomes": ["安全完成"], "requirement_ids": ["r-safe"]}
        ],
        "architecture": {
            "functions": [{"id": "f-pressure", "name": "压力控制", "requirement_ids": ["r-safe"]}],
            "logical_components": [{"id": "l-control", "name": "控制逻辑", "requirement_ids": ["r-safe"]}],
            "physical_components": [{"id": "p-sensor", "name": "压力传感器", "requirement_ids": ["r-safe"]}],
            "interfaces": [],
            "relations": [],
        },
        "open_questions": [],
    }


def test_request_is_one_domain_neutral_payload():
    request = build_project_analysis_request(_state())

    assert request.lens_id == "project_analysis"
    assert len(request.user_payload["input_regions"]) == 1
    assert "pack_id" not in request.user_payload
    assert "urban-medical-aam-v1" not in str(request.user_payload)
    assert "飞行汽车" not in request.system_prompt


def test_response_creates_domain_objects_and_rflp_architecture():
    payload = _payload()
    response = GenerationResponse(
        "project_analysis",
        payload,
        canonical_hash({}),
        canonical_hash(payload),
        False,
    )

    result = apply_project_analysis(_state(), response)

    assert result["system_context"]["domain"] == "医疗器械"
    assert result["stakeholders"][0]["name"] == "患者"
    assert result["scenarios"][0]["producer"] == "llm"
    assert result["discovery"]["architecture"]["functions"]
    assert all(item["status"] == "accepted" for item in result["claims"])


def test_response_drops_unknown_scenario_requirement_reference():
    payload = _payload()
    payload["scenarios"][0]["requirement_ids"].append("foreign-requirement")
    response = GenerationResponse(
        "project_analysis",
        payload,
        canonical_hash({}),
        canonical_hash(payload),
        False,
    )

    result = apply_project_analysis(_state(), response)

    assert result["scenarios"][0]["requirement_ids"]
    assert all("foreign-requirement" != value for value in result["scenarios"][0]["requirement_ids"])


def test_response_fills_missing_labels_without_unnamed_placeholders():
    payload = _payload()
    payload["stakeholders"] = [{"id": "s1", "category": "end_user"}]
    payload["concerns"] = [{"id": "c1", "stakeholder_id": "s1"}]
    payload["needs"] = [{"id": "n1", "stakeholder_id": "s1", "concern_id": "c1"}]
    payload["requirements"] = [{"id": "r1"}]
    payload["scenarios"] = [{"id": "sc1", "scenario_type": "failure", "description": "停止并报警"}]
    response = GenerationResponse(
        "project_analysis",
        payload,
        canonical_hash({}),
        canonical_hash(payload),
        False,
    )

    result = apply_project_analysis(_state(), response)

    values = [
        result["stakeholders"][0]["name"],
        result["concerns"][0]["name"],
        result["needs"][0]["name"],
        result["claims"][0]["object"],
        result["scenarios"][0]["title"],
    ]
    assert all(value and "未命名" not in value for value in values)
