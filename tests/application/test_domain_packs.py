from pathlib import Path

import pytest

from rflp_lite.application.domain_packs import domain_pack_hash, load_domain_pack, validate_domain_pack
from rflp_lite.domain.errors import ContractViolation


PACK_PATH = Path("src/rflp_lite/resources/domain-packs/fixed-wing-v1.json")


def test_fixed_wing_pack_is_versioned_and_has_three_disciplines():
    pack = load_domain_pack(PACK_PATH)
    assert (pack["id"], pack["version"], pack["id_prefix"]) == ("fixed-wing", 1, "FW")
    assert {item["id"] for item in pack["disciplines"]} == {
        "aerodynamics", "structures", "weight_balance"
    }
    assert len(pack["parameters"]) == 13
    assert domain_pack_hash(pack) == domain_pack_hash(load_domain_pack(PACK_PATH))


def test_pack_rejects_executable_formula_and_core_override():
    payload = {
        "id": "bad", "version": 1, "object_type": "layout", "id_prefix": "B",
        "parameters": [],
        "derived_parameters": [{"name": "x", "formula": "__import__('os').system('id')", "unit": "1"}],
        "constraints": [], "mappings": {"customer_id": {"parameter": "id"}},
        "retrieval": {"features": []}, "generation": {}, "objectives": [], "disciplines": [],
    }
    with pytest.raises(ContractViolation, match="formula|core field"):
        validate_domain_pack(payload)


def test_pack_rejects_core_override_even_when_formula_is_safe():
    payload = {
        "id": "bad", "version": 1, "object_type": "layout", "id_prefix": "B",
        "parameters": [], "derived_parameters": [], "constraints": [],
        "mappings": {"customer_id": {"parameter": "id"}},
        "retrieval": {"features": []}, "generation": {}, "objectives": [], "disciplines": [],
    }
    with pytest.raises(ContractViolation, match="core field"):
        validate_domain_pack(payload)


def test_pack_rejects_unknown_nested_approval_field():
    pack = load_domain_pack(PACK_PATH)
    pack["disciplines"][0]["formal_approved"] = True
    with pytest.raises(ContractViolation, match="unknown fields|formal_approved"):
        validate_domain_pack(pack)


@pytest.mark.parametrize("formula", ["x ** 9", "x ** -9"])
def test_pack_caps_literal_formula_exponents(formula):
    payload = {
        "id": "bad", "version": 1, "object_type": "layout", "id_prefix": "B",
        "parameters": [{"name": "x", "unit": "1", "type": "number", "required": True}],
        "derived_parameters": [{"name": "y", "formula": formula, "unit": "1"}],
        "constraints": [], "mappings": {}, "retrieval": {"features": []},
        "generation": {}, "objectives": [], "disciplines": [],
    }
    with pytest.raises(ContractViolation, match="exponent"):
        validate_domain_pack(payload)

