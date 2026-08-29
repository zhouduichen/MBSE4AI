from __future__ import annotations

from rflp_lite.application.intelligence.semantic_validator import AnalysisSemanticValidator
from rflp_lite.application.intelligence.validated_result import validate_and_build_result
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.ports.generative_model import GenerationResponse


def _state() -> dict[str, object]:
    return {
        "project_scope": {"workspace": "demo", "input_hash": "input-1"},
        "document_regions": [{"id": "region-1", "text": "系统"}],
        "structured_requirements": [{"id": "req-1", "status": "accepted"}],
        "discovery": {},
    }


def _result(payload: dict[str, object], block_id: str = "architecture"):
    response = GenerationResponse(
        f"project_analysis.{block_id}", payload, canonical_hash({}), canonical_hash(payload), False
    )
    return validate_and_build_result(response, state=_state(), block_id=block_id)


def test_unknown_relation_is_rejected() -> None:
    result = _result({
        "items": [{
            "kind": "relation", "id": "rel-1", "source_id": "req-1",
            "predicate": "invented", "target_id": "fn-1",
            "source_region_ids": ["region-1"], "confidence": 0.8,
        }],
        "diagnostics": [],
    })
    issues = AnalysisSemanticValidator().validate(result, _state())
    assert issues[0]["code"] == "unknown_relation_kind"


def test_relation_with_missing_endpoint_is_rejected() -> None:
    result = _result({
        "items": [{
            "kind": "relation", "id": "rel-1", "source_id": "req-1",
            "predicate": "satisfiedBy", "target_id": "fn-missing",
            "source_region_ids": ["region-1"], "confidence": 0.8,
        }],
        "diagnostics": [],
    })
    issues = AnalysisSemanticValidator().validate(result, _state())
    assert issues[0]["code"] == "relation_endpoint_not_found"


def test_invalid_source_region_is_rejected() -> None:
    result = _result({
        "items": [{
            "kind": "function", "id": "fn-1", "name": "执行",
            "description": "执行功能", "requirement_ids": ["req-1"],
            "source_region_ids": ["region-missing"], "confidence": 0.8,
        }],
        "diagnostics": [],
    })
    issues = AnalysisSemanticValidator().validate(result, _state())
    assert issues[0]["code"] == "source_region_not_found"
