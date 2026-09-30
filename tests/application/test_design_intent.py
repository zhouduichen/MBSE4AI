from __future__ import annotations

from rflp_lite.application.design_intent import DesignIntentService


def test_housing_intent_extracts_shell_profile_and_requires_wall_thickness():
    service = DesignIntentService()

    complete = service.create_draft(
        "p",
        "生成铝合金壳体，长120毫米，宽80毫米，高60毫米，壁厚2毫米"
    )
    incomplete = service.create_draft(
        "p",
        "生成铝合金壳体，长120毫米，宽80毫米，高60毫米"
    )

    assert complete.intent.target_kind == "housing"
    assert dict(complete.intent.parameters)["wall_thickness_mm"] == 2.0
    assert complete.status == "ready"
    assert any("壁厚" in item.question for item in incomplete.clarifications)
    assert incomplete.status == "needs_clarification"


def test_shaft_intent_extracts_step_parameters():
    draft = DesignIntentService().create_draft(
        "p",
        "生成阶梯轴，直径20毫米，长度100毫米，阶梯直径14毫米，阶梯长度30毫米"
    )

    assert draft.intent.target_kind == "shaft"
    assert dict(draft.intent.parameters) == {
        "diameter_mm": 20.0,
        "length_mm": 100.0,
        "step_diameter_mm": 14.0,
        "step_length_mm": 30.0,
    }
    assert draft.status == "ready"


def test_gear_intent_extracts_dimensionless_profile_parameters():
    draft = DesignIntentService().create_draft(
        "p",
        "生成钢制齿轮，模数2，齿数20，齿宽12毫米，孔径8毫米"
    )

    assert draft.intent.target_kind == "gear"
    assert dict(draft.intent.parameters) == {
        "module": 2.0,
        "teeth": 20.0,
        "face_width_mm": 12.0,
        "bore_diameter_mm": 8.0,
    }
    assert draft.status == "ready"
