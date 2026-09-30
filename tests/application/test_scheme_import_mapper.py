from __future__ import annotations

from pathlib import Path

from rflp_lite.application.domain_packs import load_domain_pack
from rflp_lite.application.scheme_import_mapper import map_scheme_rows


PACK = Path("src/rflp_lite/resources/domain-packs/fixed-wing-v1.json")


def test_mapper_normalizes_unified_fields_and_keeps_unavailable_features() -> None:
    result = map_scheme_rows(
        load_domain_pack(PACK),
        (
            {
                "scheme_id": "FW-HISTORY-001",
                "name": "巡察基准",
                "task_type": "reconnaissance",
                "span_m": "15",
                "wing_area_m2": "24",
                "fuselage_length_m": "9",
                "mtow_kg": "650",
                "empty_mass_kg": "540",
                "payload_kg": "180",
                "range_km": "500",
                "cruise_speed_kmh": "240",
                "section_modulus_m3": "0.03",
                "allowable_stress_pa": "200000000",
                "cg_x_m": "2.7",
            },
        ),
        "demo-schemes.json",
    )

    record = result.records[0]
    assert record.id == "FW-HISTORY-001"
    assert dict(record.parameters)["mass_kg"] == 540.0
    assert dict(record.parameters)["cruise_speed_mps"] == 240 / 3.6
    extensions = dict(record.extensions)
    assert extensions["name"] == "巡察基准"
    assert extensions["task_type"] == "reconnaissance"
    assert extensions["mtow_kg"] == "650"
    assert extensions["range_km"] == "500"


def test_mapper_reports_existing_stable_ids_as_skipped() -> None:
    row = {"scheme_id": "FW-HISTORY-001", "name": "巡察基准", "empty_mass_kg": 540}

    first = map_scheme_rows(load_domain_pack(PACK), (row,), "demo-schemes.json")
    second = map_scheme_rows(
        load_domain_pack(PACK),
        (row,),
        "demo-schemes.json",
        existing_ids={first.records[0].id},
    )

    assert second.records == ()
    assert second.skipped == ("FW-HISTORY-001",)

