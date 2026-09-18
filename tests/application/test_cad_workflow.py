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
    assert len(draft.payload["structure_options"]) >= 2
    assert {item["status"] for item in draft.payload["structure_options"]} == {"recommendation"}
    assert plan["selected_structure_option_id"] == ""
    assert "add_rib" not in {item["operation"] for item in plan["operations"]}
    assert "add_fillet" not in {item["operation"] for item in plan["operations"]}
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


def test_structure_option_selection_is_validated_and_traced(tmp_path: Path):
    services = build_v2_services(tmp_path)
    services.projects.create("p")
    cad = services.cad_design("p")

    draft = cad.create_intent("生成铝合金支架，长100毫米，宽50毫米，高10毫米")
    selected = draft.payload["structure_options"][0]["id"]
    plan = cad.create_plan(draft.draft_id, selected_structure_option_id=selected)
    assert plan["selected_structure_option_id"] == selected
    assert plan["intent"]["structure_options"][0]["id"] == selected
    with pytest.raises(ContractViolation):
        cad.create_plan(draft.draft_id, selected_structure_option_id="not-an-option")

    cad.approve_plan(plan["id"])
    model = cad.execute_plan(plan["id"])
    assert model["selected_structure_option_id"] == selected
    applied = cad.apply_model(model["id"])
    payload = applied["entity"]["payload"]
    assert payload["selected_structure_option_id"] == selected
    assert payload["design_intent"]["structure_options"][0]["id"] == selected


def test_structure_option_changes_parameterized_cad_operations(tmp_path: Path):
    services = build_v2_services(tmp_path)
    services.projects.create("p")
    cad = services.cad_design("p")
    draft = cad.create_intent("生成铝合金支架，长100毫米，宽50毫米，高10毫米")

    ribbed = cad.create_plan(
        draft.draft_id,
        selected_structure_option_id="bracket-gusseted-plate",
    )
    block = cad.create_plan(
        draft.draft_id,
        selected_structure_option_id="bracket-machined-block",
    )

    ribbed_operations = [item["operation"] for item in ribbed["operations"]]
    block_operations = [item["operation"] for item in block["operations"]]
    assert ribbed_operations.count("add_rib") == 2
    assert "add_fillet" not in ribbed_operations
    assert block_operations.count("add_fillet") == 1
    assert "add_rib" not in block_operations
    assert ribbed["preview"]["parts"][0]["bbox_mm"][2] > 10
    assert [item["kind"] for item in ribbed["preview"]["parts"][0]["features"]][-2:] == ["add_rib", "add_rib"]
    assert block["preview"]["parts"][0]["features"][-1]["kind"] == "add_fillet"
    assert ribbed["preview_hash"] != block["preview_hash"]


def test_profile_intents_compile_to_shell_shaft_and_gear_operations(tmp_path: Path):
    services = build_v2_services(tmp_path)
    services.projects.create("p")
    cad = services.cad_design("p")

    housing = cad.create_intent(
        "生成铝合金壳体，长120毫米，宽80毫米，高60毫米，壁厚2毫米"
    )
    shaft = cad.create_intent(
        "生成阶梯轴，直径20毫米，长度100毫米，阶梯直径14毫米，阶梯长度30毫米"
    )
    gear = cad.create_intent(
        "生成钢制齿轮，模数2，齿数20，齿宽12毫米，孔径8毫米"
    )

    housing_plan = cad.create_plan(housing.draft_id)
    shaft_plan = cad.create_plan(shaft.draft_id)
    gear_plan = cad.create_plan(gear.draft_id)

    assert housing_plan["status"] == "ready"
    assert [item["operation"] for item in housing_plan["operations"]] == [
        "create_part", "create_shell", "set_material",
    ]
    assert [item["operation"] for item in shaft_plan["operations"]] == [
        "create_part", "create_cylinder", "add_shaft_step",
    ]
    assert [item["operation"] for item in gear_plan["operations"]] == [
        "create_part", "create_gear", "set_material",
    ]


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


def test_design_rule_review_reports_profile_findings(tmp_path: Path):
    services = build_v2_services(tmp_path)
    services.projects.create("p")
    review = services.design_review("p").review(
        "profile-defect",
        {
            "parts": [{
                "id": "gear",
                "material": "钢",
                "bbox_mm": [44, 44, 12],
                "features": [{
                    "id": "gear-feature",
                    "kind": "create_gear",
                    "parameters": {"module": 2, "teeth": 20, "face_width_mm": 12, "bore_diameter_mm": 0},
                }],
            }],
        },
    )

    assert review["status"] == "needs_review"
    assert any(item["rule_id"] == "dfm.gear_bore" for item in review["findings"])
