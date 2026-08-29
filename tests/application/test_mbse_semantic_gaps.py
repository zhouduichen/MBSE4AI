from __future__ import annotations

from rflp_lite.application.mbse_semantics import build_mbse_semantic_model


def _state() -> dict[str, object]:
    return {
        "revision": 1,
        "project_scope": {"workspace": "demo", "input_hash": "input-1"},
        "document_regions": [{"id": "region-1", "text": "系统必须安全运行"}],
        "structured_requirements": [{
            "id": "req-1", "statement": "系统必须安全运行", "status": "accepted",
            "verification_method": "analysis", "source_region_id": "region-1",
        }],
        "stakeholders": [], "concerns": [], "needs": [], "scenarios": [],
        "discovery": {},
    }


def test_missing_architecture_is_gap_not_fabricated_realization() -> None:
    model = build_mbse_semantic_model(_state())
    assert model["sections"]["functional"]["functions"] == []
    assert model["sections"]["logical"]["components"] == []
    assert model["sections"]["physical"]["components"] == []
    assert model["sections"]["functional"]["gaps"]
    assert model["sections"]["logical"]["gaps"]
    assert model["sections"]["physical"]["gaps"]
    assert not {
        relation["kind"]
        for relation in model["relations"]
    } & {"satisfiedBy", "allocatedTo", "realizedBy"}


def test_explicit_architecture_evidence_creates_only_declared_relations() -> None:
    state = _state()
    state["discovery"] = {
        "architecture": {
            "functions": [{"id": "fn-1", "name": "安全运行", "requirement_ids": ["req-1"], "producer": "llm"}],
            "logical_components": [{"id": "logic-1", "name": "安全控制", "producer": "llm"}],
            "physical_components": [{"id": "physical-1", "name": "控制器", "producer": "manual"}],
            "interfaces": [],
            "relations": [
                {"source_id": "fn-1", "predicate": "allocatedTo", "target_id": "logic-1", "producer": "manual"},
                {"source_id": "logic-1", "predicate": "realizedBy", "target_id": "physical-1", "producer": "manual"},
            ],
        }
    }
    model = build_mbse_semantic_model(state)
    formal = {(item["kind"], item["source_id"], item["target_id"]) for item in model["relations"]}
    assert ("satisfiedBy", "req-1", "fn-1") in formal
    assert ("allocatedTo", "fn-1", "logic-1") in formal
    assert ("realizedBy", "logic-1", "physical-1") in formal
