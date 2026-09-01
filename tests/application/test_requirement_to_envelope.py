from pathlib import Path

import pytest

from rflp_lite.application.domain_packs import load_domain_pack
from rflp_lite.application.requirement_to_envelope import build_envelope_from_requirements


PACK = Path("src/rflp_lite/resources/domain-packs/fixed-wing-v1.json")


@pytest.fixture
def fixed_wing_pack():
    return load_domain_pack(PACK)


@pytest.fixture
def history():
    return ({
        "id": "HIST-01",
        "parameters": {
            "mass_kg": 540,
            "payload_kg": 180,
            "wing_area_m2": 24,
            "span_m": 13,
            "fuselage_length_m": 9,
            "cruise_speed_mps": 65,
            "section_modulus_m3": 0.03,
            "allowable_stress_pa": 200000000,
            "cg_x_m": 2.7,
        },
    },)


def test_build_envelope_maps_explicit_bounds_and_source_ids(fixed_wing_pack, history):
    result = build_envelope_from_requirements(
        fixed_wing_pack,
        [
            {"id": "REQ-MASS", "status": "accepted", "statement": "最大起飞重量不超过500kg"},
            {"id": "REQ-SPAN", "status": "accepted", "statement": "翼展不超过12m"},
            {"id": "REQ-PAYLOAD", "status": "accepted", "statement": "任务载荷不低于50kg"},
        ],
        history=history,
    )
    assert set(result.envelope.source_requirement_ids) == {
        "REQ-MASS", "REQ-SPAN", "REQ-PAYLOAD"
    }
    span_bound = next(item[1:] for item in result.envelope.bounds if item[0] == "span_m")
    assert span_bound == (5.0, 12.0)
    assert {item.source_kind for item in result.field_provenance} >= {"explicit", "suggested"}


def test_cruise_speed_converts_kmh_to_pack_mps(fixed_wing_pack, history):
    result = build_envelope_from_requirements(
        fixed_wing_pack,
            [{"id": "REQ-SPEED", "status": "accepted", "statement": "巡航速度不低于180km/h"}],
        history=history,
    )
    speed_bound = next(item[1:] for item in result.envelope.bounds if item[0] == "cruise_speed_mps")
    assert speed_bound[0] == pytest.approx(50.0)


def test_missing_range_parameter_is_diagnostic_not_silent_mapping(fixed_wing_pack, history):
    result = build_envelope_from_requirements(
        fixed_wing_pack,
        [{"id": "REQ-RANGE", "status": "accepted", "statement": "航程不低于800km"}],
        history=history,
    )
    assert not any(name == "range_km" for name, _value in result.envelope.parameters)
    assert any("range_km" in item for item in result.diagnostics)


def test_unreviewed_requirement_does_not_create_explicit_bound(fixed_wing_pack, history):
    result = build_envelope_from_requirements(
        fixed_wing_pack,
        [{"id": "REQ-DRAFT", "status": "candidate", "statement": "翼展不超过12m"}],
        history=history,
    )
    assert not any(item.parameter == "span_m" and item.source_kind == "explicit" for item in result.field_provenance)
