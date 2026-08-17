from rflp_lite.application.mbse_domain_packs import list_domain_packs, load_domain_pack


EXPECTED_BROAD_PACKS = {
    "medical-v1",
    "aviation-v1",
    "automotive-v1",
    "industrial-v1",
    "energy-infrastructure-v1",
    "software-data-v1",
    "mechanical-v1",
    "electrical-v1",
    "software-v1",
    "control-v1",
    "thermal-v1",
    "safety-v1",
    "manufacturing-v1",
}


def test_broad_pack_catalog_is_available():
    assert EXPECTED_BROAD_PACKS <= set(list_domain_packs())


def test_each_broad_pack_has_reusable_coverage_contract():
    for pack_id in sorted(EXPECTED_BROAD_PACKS):
        pack = load_domain_pack(pack_id)
        assert len(pack["stakeholder_lenses"]) >= 5
        assert len(pack["lifecycle_phases"]) >= 5
        assert len(pack["scenario_dimensions"]) >= 5
        assert len(pack["coverage_rules"]) >= 5
        assert len(pack["prompt_fragments"]) >= 5
        assert pack["extensions"]["reusable"] is True


def test_urban_medical_aam_keeps_composition_declaration_as_overlay():
    pack = load_domain_pack("urban-medical-aam-v1")
    assert pack["extends"] == ["medical-v1", "aviation-v1"]
    assert pack["disciplines"] == [
        "mechanical-v1",
        "electrical-v1",
        "control-v1",
        "safety-v1",
    ]
    assert len(pack["scenario_dimensions"]) >= 5
    assert len(pack["coverage_rules"]) >= 5
    assert len(pack["prompt_fragments"]) >= 5
