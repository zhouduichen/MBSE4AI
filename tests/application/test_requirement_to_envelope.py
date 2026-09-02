from __future__ import annotations

from pathlib import Path

from rflp_lite.application.domain_packs import load_domain_pack
from rflp_lite.application.requirement_to_envelope import build_envelope_from_requirements


PACK = Path("src/rflp_lite/resources/domain-packs/fixed-wing-v1.json")


def _attribute(requirement_id: str, name: str, *, value: str = "", unit: str = "", minimum: str = "", maximum: str = "") -> dict[str, object]:
    return {
        "requirement_id": requirement_id,
        "name": name,
        "value": value,
        "unit": unit,
        "minimum": minimum,
        "maximum": maximum,
        "source_region_ids": [f"region-{requirement_id}"],
    }


def test_builds_explicit_envelope_with_units_and_field_provenance() -> None:
    requirements = [
        {"id": "REQ-MASS", "status": "accepted"},
        {"id": "REQ-PAYLOAD", "status": "accepted"},
        {"id": "REQ-SPAN", "status": "accepted"},
        {"id": "REQ-SPEED", "status": "accepted"},
        {"id": "REQ-GEOMETRY", "status": "accepted"},
    ]
    attributes = (
        _attribute("REQ-MASS", "最大起飞重量", maximum="650", unit="kg"),
        _attribute("REQ-PAYLOAD", "任务载荷", minimum="150", unit="kg"),
        _attribute("REQ-SPAN", "翼展", maximum="16", unit="m"),
        _attribute("REQ-SPEED", "巡航速度", minimum="240", unit="km/h"),
        _attribute("REQ-GEOMETRY", "机翼面积", value="24", unit="m2"),
        _attribute("REQ-GEOMETRY", "机身长度", value="9", unit="m"),
        _attribute("REQ-GEOMETRY", "截面模量", value="0.032", unit="m3"),
        _attribute("REQ-GEOMETRY", "许用应力", value="205000000", unit="Pa"),
        _attribute("REQ-GEOMETRY", "重心位置", value="2.7", unit="m"),
    )

    result = build_envelope_from_requirements(load_domain_pack(PACK), requirements, attributes=attributes)

    values = dict(result.envelope.parameters)
    provenance = {item.parameter: item for item in result.field_provenance}
    assert values["cruise_speed_mps"] == 240 / 3.6
    assert next(item[1:] for item in result.envelope.bounds if item[0] == "span_m") == (5.0, 16.0)
    assert provenance["cruise_speed_mps"].source_kind == "explicit"
    assert provenance["cruise_speed_mps"].requirement_ids == ("REQ-SPEED",)
    assert "REQ-MASS" in result.envelope.source_requirement_ids


def test_missing_semantic_target_is_diagnostic_and_history_is_suggested() -> None:
    pack = load_domain_pack(PACK)
    result = build_envelope_from_requirements(
        pack,
        [{"id": "REQ-RANGE", "status": "accepted"}],
        attributes=(_attribute("REQ-RANGE", "航程", minimum="500", unit="km"),),
        history=(
            {
                "id": "HISTORY-1",
                "parameters": [
                    ["section_modulus_m3", 0.03],
                    ["allowable_stress_pa", 200000000],
                    ["cg_x_m", 2.7],
                ],
            },
        ),
    )

    assert result.envelope is None
    assert any("航程" in diagnostic or "range" in diagnostic for diagnostic in result.diagnostics)
    suggested = {item.parameter: item for item in result.field_provenance if item.source_kind == "suggested"}
    assert suggested["section_modulus_m3"].requirement_ids == ()


def test_explicit_values_override_conflicting_llm_suggestions() -> None:
    pack = load_domain_pack(PACK)
    result = build_envelope_from_requirements(
        pack,
        [{"id": "REQ-SPEED", "status": "accepted"}],
        attributes=(_attribute("REQ-SPEED", "巡航速度", value="100", unit="m/s"),),
        llm_suggestions=({"name": "cruise_speed_mps", "value": 40, "unit": "m/s"},),
        provisional=True,
    )

    assert result.envelope is not None
    assert dict(result.envelope.parameters)["cruise_speed_mps"] == 100
    provenance = {item.parameter: item for item in result.field_provenance}
    assert provenance["cruise_speed_mps"].source_kind == "explicit"


def test_provisional_mode_fills_missing_required_values_without_history() -> None:
    pack = load_domain_pack(PACK)
    result = build_envelope_from_requirements(
        pack,
        [{"id": "REQ-INTENT", "status": "accepted"}],
        llm_suggestions=({
            "name": "mass_kg",
            "value": 650,
            "unit": "kg",
            "producer": "llm",
            "candidate_type": "suggested",
        },),
        provisional=True,
    )

    assert result.envelope is not None
    assert dict(result.envelope.parameters)["mass_kg"] == 650
    assert dict(result.envelope.parameters)["wing_area_m2"] == 52.5
    assert result.envelope.status == "candidate"
    provenance = {item.parameter: item for item in result.field_provenance}
    assert provenance["mass_kg"].source_kind == "suggested_llm"
    assert provenance["wing_area_m2"].source_kind == "suggested_default"


def test_invalid_llm_suggestions_are_diagnostic_and_strict_mode_stays_strict() -> None:
    pack = load_domain_pack(PACK)
    provisional = build_envelope_from_requirements(
        pack,
        [{"id": "REQ-INTENT", "status": "accepted"}],
        llm_suggestions=({"name": "mass_kg", "value": -1, "unit": "kg"},),
        provisional=True,
    )
    strict = build_envelope_from_requirements(
        pack,
        [{"id": "REQ-INTENT", "status": "accepted"}],
    )

    assert provisional.envelope is not None
    assert any("mass_kg" in item for item in provisional.diagnostics)
    assert strict.envelope is None
