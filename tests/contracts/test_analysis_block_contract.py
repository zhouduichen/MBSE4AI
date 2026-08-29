from __future__ import annotations

import pytest

from rflp_lite.application.intelligence.block_schemas import BLOCK_SCHEMA_VERSION, schema_for
from rflp_lite.application.intelligence.semantic_validator import AnalysisSemanticValidator
from rflp_lite.application.intelligence.validated_result import parse_block_dto, validate_and_build_result
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.ports.generative_model import GenerationResponse


def _state() -> dict[str, object]:
    return {
        "project_scope": {"workspace": "alpha", "input_hash": "input-1"},
        "document_regions": [{"id": "region-1", "text": "系统"}],
        "structured_requirements": [{"id": "req-1", "status": "accepted"}],
        "discovery": {},
    }


def _item(block_id: str) -> dict[str, object]:
    common = {"source_region_ids": ["region-1"], "confidence": 0.9}
    if block_id == "system_scope":
        return {"id": "scope-1", "name": "系统", "domain": "通用", "mission": "完成任务", **common}
    if block_id == "stakeholders":
        return {"id": "stakeholder-1", "name": "操作员", "category": "operator", "goals": ["操作"], "interactions": ["输入"], **common}
    if block_id == "concerns_needs":
        return {"kind": "concern", "id": "concern-1", "name": "安全", "stakeholder_id": "stakeholder-1", **common}
    if block_id == "requirements":
        return {"id": "requirement-1", "statement": "系统应完成任务", "subject": "系统", "predicate": "应", "verification_method": "测试", **common}
    if block_id == "scenarios":
        return {"id": "scenario-1", "title": "正常任务", "scenario_type": "normal", "actors": ["操作员"], "steps": ["执行"], "expected_outcomes": ["完成"], "requirement_ids": ["req-1"], **common}
    return {"kind": "function", "id": "function-1", "name": "执行任务", "description": "执行任务功能", "requirement_ids": ["req-1"], **common}


@pytest.mark.parametrize("block_id", ("system_scope", "stakeholders", "concerns_needs", "requirements", "scenarios", "architecture"))
def test_each_block_has_a_strict_contract(block_id: str) -> None:
    payload = {"schema_version": BLOCK_SCHEMA_VERSION, "items": [_item(block_id)], "diagnostics": []}
    dto = parse_block_dto(block_id, payload)
    assert dto.block_id == block_id
    assert schema_for(block_id)["additionalProperties"] is False


def test_extra_fields_and_invalid_confidence_are_rejected() -> None:
    payload = {"items": [{**_item("stakeholders"), "unapproved": True}], "diagnostics": []}
    with pytest.raises(ContractViolation, match="Strict Schema"):
        parse_block_dto("stakeholders", payload)

    payload = {"items": [{**_item("stakeholders"), "confidence": 1.5}], "diagnostics": []}
    with pytest.raises(ContractViolation, match="Strict Schema"):
        parse_block_dto("stakeholders", payload)


def test_validated_result_rejects_cross_workspace_and_semantic_relation() -> None:
    payload = {
        "workspace": "beta",
        "items": [_item("architecture")],
        "diagnostics": [],
    }
    response = GenerationResponse("project_analysis.architecture", payload, "input-1", canonical_hash(payload), False)
    with pytest.raises(ContractViolation, match="workspace"):
        validate_and_build_result(response, state=_state(), block_id="architecture")

    payload = {
        "items": [{
            "kind": "relation", "id": "rel-1", "source_id": "req-1", "predicate": "satisfiedBy",
            "target_id": "missing", "source_region_ids": ["region-1"], "confidence": 0.9,
        }],
        "diagnostics": [],
    }
    response = GenerationResponse("project_analysis.architecture", payload, "input-1", canonical_hash(payload), False)
    result = validate_and_build_result(response, state=_state(), block_id="architecture")
    issues = AnalysisSemanticValidator().validate(result, _state())
    assert issues[0]["code"] == "relation_endpoint_not_found"


def test_declared_block_id_cannot_cross_block_boundaries() -> None:
    payload = {"block_id": "requirements", "items": [_item("stakeholders")], "diagnostics": []}
    response = GenerationResponse("project_analysis.stakeholders", payload, "input-1", canonical_hash(payload), False)
    with pytest.raises(ContractViolation, match="block_id"):
        validate_and_build_result(response, state=_state(), block_id="stakeholders")
