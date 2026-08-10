from pathlib import Path

import pytest

from rflp_lite.application.domain_packs import load_domain_pack
from rflp_lite.application.scheme_library import import_scheme_rows


PACK_PATH = Path("src/rflp_lite/resources/domain-packs/fixed-wing-v1.json")


@pytest.fixture()
def pack():
    return load_domain_pack(PACK_PATH)


def test_import_maps_aliases_and_preserves_unknown_fields(pack):
    batch = import_scheme_rows(
        pack,
        ({"方案名称": "A", "空机质量": "120", "客户备注": "baseline"},),
        "customer.csv:2",
    )
    record = batch.records[0]
    assert dict(record.parameters)["mass_kg"] == 120.0
    assert dict(record.extensions)["客户备注"] == "baseline"
    assert record.id.startswith("FW-S-")
    assert batch.rejected == ()


def test_invalid_rows_are_isolated_without_losing_valid_rows(pack):
    batch = import_scheme_rows(pack, ({"mass_kg": "bad"}, {"mass_kg": "120"}), "x.csv")
    assert len(batch.records) == 1
    assert batch.rejected[0]["row"] == 1


def test_number_mapping_applies_units_and_declared_defaults(pack):
    batch = import_scheme_rows(
        pack,
        ({"mass_kg": {"value": 120_000, "unit": "g"}},),
        "x.json",
    )
    record = batch.records[0]
    assert dict(record.parameters)["mass_kg"] == 120.0
    # Optional parameter defaults are filled from the declaration.
    assert dict(record.parameters)["air_density_kg_m3"] == 1.225
