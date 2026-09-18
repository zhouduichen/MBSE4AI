from __future__ import annotations

from pathlib import Path

import pytest

from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.errors import ContractViolation


def test_design_intent_requires_clarification_before_cad_execution(tmp_path: Path):
    services = build_v2_services(tmp_path)
    services.projects.create("p")
    cad = services.cad_design("p")

    draft = cad.create_intent("生成一个零件")
    assert draft.status == "needs_clarification"
    plan = cad.create_plan(draft.draft_id)
    with pytest.raises(ContractViolation):
        cad.approve_plan(plan["id"])


def test_cad_plan_execute_review_and_apply_are_idempotent(tmp_path: Path):
    services = build_v2_services(tmp_path)
    services.projects.create("p")
    cad = services.cad_design("p")

    draft = cad.create_intent("生成铝合金支架，长100毫米，宽50毫米，高10毫米")
    plan = cad.create_plan(draft.draft_id)
    assert plan["status"] == "ready"
    assert plan["preview"]["schema_version"] == "parametric-cad-preview.v1"
    with pytest.raises(ContractViolation):
        cad.execute_plan(plan["id"])

    cad.approve_plan(plan["id"])
    model = cad.execute_plan(plan["id"])
    repeated_model = cad.execute_plan(plan["id"])
    assert repeated_model["idempotent"] is True
    assert model["model_payload"]["obj"]
    assert model["model_payload"]["open_scad_source"]

    review = services.design_review("p").review(model["id"], model["model_payload"])
    assert review["status"] == "passed"
    assert {"top", "isometric"} <= set(review["annotations"][0]["views"])
    assert review["artifacts"]["drawing_svg"].startswith("<svg")
    assert review["artifacts"]["drawing_hash"]
    assert review["artifacts"]["source_kind"] == "development"
    assert services.design_review("p").review(model["id"], model["model_payload"])["idempotent"] is True

    applied = cad.apply_model(model["id"])
    assert applied["entity"]["kind"] == EntityKind.PHYSICAL_BLOCK.value
    assert cad.apply_model(model["id"])["idempotent"] is True


def test_design_rule_review_reports_feature_location_and_version(tmp_path: Path):
    services = build_v2_services(tmp_path)
    services.projects.create("p")
    review = services.design_review("p").review(
        "model-defect",
        {
            "parts": [{
                "id": "bracket",
                "material": "钢",
                "bbox_mm": [100, 50, 10],
                "features": [{
                    "id": "hole-1",
                    "kind": "add_hole",
                    "parameters": {"diameter_mm": 10, "edge_distance_mm": 5, "tool_access": False},
                }],
            }],
        },
    )
    assert review["status"] == "needs_review"
    assert review["rule_version"] == "dfm-dfa-preview-1.0"
    assert {item["rule_id"] for item in review["findings"]} >= {"dfm.hole_edge_distance", "dfa.tool_access"}
    assert all(item["location"] for item in review["findings"])
