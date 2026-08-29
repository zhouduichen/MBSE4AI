from __future__ import annotations

import pytest

from rflp_lite.application.intelligence.validated_result import validate_and_build_result
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.ports.generative_model import GenerationResponse


def _state() -> dict[str, object]:
    return {
        "project_scope": {"workspace": "demo", "input_hash": "input-1"},
        "document_regions": [{"id": "region-1", "text": "系统"}],
    }


def _response(payload: dict[str, object]) -> GenerationResponse:
    return GenerationResponse(
        "project_analysis.stakeholders",
        payload,
        canonical_hash({}),
        canonical_hash(payload),
        False,
    )


def test_valid_result_carries_workspace_and_schema_provenance() -> None:
    payload = {
        "items": [{
            "id": "sh-1", "name": "操作员", "category": "operator",
            "goals": ["操作"], "interactions": ["输入"],
            "source_region_ids": ["region-1"], "confidence": 0.8,
        }],
        "diagnostics": [],
    }
    result = validate_and_build_result(_response(payload), state=_state(), block_id="stakeholders")
    assert result.input_hash == "input-1"
    assert result.workspace == "demo"
    assert result.provenance["schema_version"] == "v2"


def test_foreign_input_hash_is_rejected() -> None:
    payload = {
        "input_hash": "other",
        "items": [{
            "id": "sh-1", "name": "操作员", "category": "operator",
            "goals": ["操作"], "interactions": ["输入"],
            "source_region_ids": ["region-1"], "confidence": 0.8,
        }],
        "diagnostics": [],
    }
    with pytest.raises(ContractViolation, match="input_hash"):
        validate_and_build_result(_response(payload), state=_state(), block_id="stakeholders")
