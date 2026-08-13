from rflp_lite.application.intelligence.intake import attach_seed_model, build_seed_model


PACK = {"id": "urban-medical-aam-v1", "display_name": "城市医疗飞行汽车"}


def test_one_sentence_builds_a_named_seed_and_preserves_source():
    state = {
        "schema_version": 3,
        "document_regions": [
            {"id": "region-1", "artifact_id": "artifact-1", "text": "设计一款城市医疗用途的飞行汽车"}
        ],
        "discovery": {"intake": {}, "revision": 0},
    }
    seed = build_seed_model(state, PACK)
    assert seed["system_name"] == "城市医疗用途的飞行汽车"
    assert seed["application_type"] == "城市医疗"
    assert seed["source_region_ids"] == ["region-1"]
    assert "operating_boundary" in seed["unknowns"]


def test_attach_seed_increments_discovery_revision_without_mutating_input():
    source = {
        "document_regions": [{"id": "r1", "text": "城市医疗飞行汽车"}],
        "discovery": {"intake": {}, "revision": 0},
    }
    updated = attach_seed_model(source, PACK)
    assert source["discovery"]["revision"] == 0
    assert updated["discovery"]["revision"] == 1
    assert updated["discovery"]["intake"]["seed_hash"]
