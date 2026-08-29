from __future__ import annotations

import math

import pytest

from rflp_lite.application.intelligence.block_schemas import schema_for
from rflp_lite.application.intelligence.validated_result import parse_block_dto
from rflp_lite.domain.errors import ContractViolation


def _base_item(block_id: str) -> dict[str, object]:
    common = {"source_region_ids": ["region-1"], "confidence": 0.8}
    if block_id == "system_scope":
        return {"id": "scope-1", "name": "系统", "domain": "软件", "mission": "完成任务", **common}
    if block_id == "stakeholders":
        return {"id": "sh-1", "name": "操作员", "category": "operator", "goals": ["操作"], "interactions": ["输入"], **common}
    if block_id == "concerns_needs":
        return {"kind": "concern", "id": "concern-1", "name": "安全", "stakeholder_id": "sh-1", **common}
    if block_id == "requirements":
        return {"id": "req-1", "statement": "系统必须可验证", "subject": "系统", "predicate": "必须", "verification_method": "测试", **common}
    if block_id == "scenarios":
        return {"id": "sc-1", "title": "正常操作", "scenario_type": "normal", "actors": ["sh-1"], "steps": ["执行"], "expected_outcomes": ["完成"], "requirement_ids": ["req-1"], **common}
    return {"kind": "function", "id": "fn-1", "name": "执行", "description": "执行功能", "requirement_ids": ["req-1"], **common}


@pytest.mark.parametrize("block_id", ["system_scope", "stakeholders", "concerns_needs", "requirements", "scenarios", "architecture"])
def test_each_block_has_strict_schema_and_typed_dto(block_id: str) -> None:
    payload = {"items": [_base_item(block_id)], "diagnostics": []}
    dto = parse_block_dto(block_id, payload)
    assert dto.block_id == block_id
    assert dto.items[0]["id"]
    assert schema_for(block_id)["additionalProperties"] is False


def test_extra_fields_are_rejected_at_item_boundary() -> None:
    payload = {"items": [{**_base_item("stakeholders"), "unexpected": True}], "diagnostics": []}
    with pytest.raises(ContractViolation, match="Strict Schema"):
        parse_block_dto("stakeholders", payload)


def test_non_finite_confidence_is_rejected() -> None:
    payload = {"items": [{**_base_item("stakeholders"), "confidence": math.nan}], "diagnostics": []}
    with pytest.raises(ContractViolation):
        parse_block_dto("stakeholders", payload)
