from __future__ import annotations

from rflp_lite.application.intelligence.analysis_blocks import merge_block_result
from rflp_lite.application.intelligence.semantic_validator import AnalysisSemanticValidator
from rflp_lite.application.intelligence.validated_result import validate_and_build_result
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.ports.generative_model import GenerationResponse


def _state(workspace: str) -> dict[str, object]:
    return {
        "project_scope": {"workspace": workspace, "input_hash": f"{workspace}-input"},
        "document_regions": [{"id": f"{workspace}-region", "text": "系统输入"}],
        "stakeholders": [],
        "discovery": {},
    }


def test_cross_workspace_payload_is_rejected() -> None:
    state = _state("alpha")
    payload = {
        "workspace": "beta",
        "items": [{
            "id": "beta-stakeholder", "name": "操作员", "category": "operator",
            "goals": ["操作"], "interactions": ["输入"],
            "source_region_ids": ["alpha-region"], "confidence": 0.8,
        }],
        "diagnostics": [],
    }
    response = GenerationResponse("project_analysis.stakeholders", payload, "alpha-input", canonical_hash(payload), False)
    try:
        validate_and_build_result(response, state=state, block_id="stakeholders")
    except ContractViolation as exc:
        assert "workspace" in str(exc)
    else:  # pragma: no cover - the contract must reject this payload
        raise AssertionError("cross-workspace block was accepted")


def test_valid_block_is_preserved_when_a_later_block_fails_semantic_validation() -> None:
    state = _state("alpha")
    stakeholder_payload = {
        "items": [{
            "id": "operator", "name": "操作员", "category": "operator",
            "goals": ["操作"], "interactions": ["输入"],
            "source_region_ids": ["alpha-region"], "confidence": 0.8,
        }],
        "diagnostics": [],
    }
    stakeholder = validate_and_build_result(
        GenerationResponse("project_analysis.stakeholders", stakeholder_payload, "alpha-input", canonical_hash(stakeholder_payload), False),
        state=state,
        block_id="stakeholders",
    )
    merged = merge_block_result(state, stakeholder)
    assert merged["stakeholders"]

    architecture_payload = {
        "items": [{
            "kind": "relation", "id": "bad-relation", "source_id": "operator",
            "predicate": "unknown", "target_id": "operator",
            "source_region_ids": ["alpha-region"], "confidence": 0.8,
        }],
        "diagnostics": [],
    }
    architecture = validate_and_build_result(
        GenerationResponse("project_analysis.architecture", architecture_payload, "alpha-input", canonical_hash(architecture_payload), False),
        state=merged,
        block_id="architecture",
    )
    issues = AnalysisSemanticValidator().validate(architecture, merged)
    assert issues and issues[0]["code"] == "unknown_relation_kind"
    assert merged["stakeholders"][0]["name"] == "操作员"
    assert "architecture" not in (merged.get("discovery") or {}).get("block_results", {})
