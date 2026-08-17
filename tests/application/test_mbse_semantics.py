import pytest

from rflp_lite.application.mbse_semantics import (
    MBSE_SEMANTIC_MODEL_VERSION,
    SEMANTIC_FORMAT,
    build_mbse_semantic_model,
    legacy_mbse_projection,
    mbse_entity_index,
    validate_mbse_semantic_model,
)
from rflp_lite.application.requirements_workbench import accept_traceable, analyze_artifact
from rflp_lite.domain.errors import ContractViolation


def _state():
    return accept_traceable(
        analyze_artifact("requirements.txt", "管理员必须恢复历史版本。".encode())
    )


def test_semantic_model_contains_all_mbse_layers_and_traceability():
    model = build_mbse_semantic_model(_state(), revision=3, provenance={"producer": "test"})

    assert model["format"] == SEMANTIC_FORMAT
    assert model["version"] == MBSE_SEMANTIC_MODEL_VERSION
    assert set(("operational", "functional", "logical", "physical")) <= set(model["sections"])
    assert model["sections"]["operational"]["stakeholders"]
    assert model["sections"]["operational"]["scenarios"]
    assert model["sections"]["functional"]["functions"]
    assert model["sections"]["logical"]["components"]
    assert model["sections"]["physical"]["components"]
    assert model["sections"]["technical_requirements"]
    assert any(item["kind"] == "satisfiedBy" for item in model["relations"])
    assert validate_mbse_semantic_model(model) == ()
    assert mbse_entity_index(model)

    legacy = legacy_mbse_projection(model)
    assert legacy["version"] == 1
    assert legacy["actors"]
    assert legacy["use_cases"]
    assert legacy["activities"]
    assert legacy["messages"]


def test_semantic_validator_rejects_unknown_relation_kind_and_endpoint():
    model = {
        "format": SEMANTIC_FORMAT,
        "version": MBSE_SEMANTIC_MODEL_VERSION,
        "sections": {
            "operational": {"items": [{"id": "a", "kind": "actor", "name": "A"}]},
            "functional": {},
            "logical": {},
            "physical": {},
            "technical_requirements": [],
        },
        "relations": [
            {
                "id": "r-1",
                "source_id": "a",
                "kind": "unknownRelation",
                "target_id": "foreign",
            }
        ],
    }

    issues = validate_mbse_semantic_model(model)

    assert any("unsupported relation kind" in issue for issue in issues)
    assert any("relation endpoint not found" in issue for issue in issues)
    with pytest.raises(ContractViolation, match="semantic model invalid"):
        legacy_mbse_projection(model)
