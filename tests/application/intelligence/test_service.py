from rflp_lite.application.intelligence.service import IntelligenceService


def pack():
    return {"id": "urban-medical-aam-v1", "display_name": "城市医疗飞行汽车", "element_schemas": {}, "stakeholder_lenses": [{"id": "medical", "label": "医疗"}], "lifecycle_phases": [{"id": "takeoff", "label": "起飞"}], "scenario_dimensions": [{"id": "weather", "label": "天气", "values": ["rain"]}], "coverage_rules": [{"id": "stakeholder-lenses", "source": "stakeholder_lenses", "priority": "high"}, {"id": "lifecycle-phases", "source": "lifecycle_phases", "priority": "high"}, {"id": "scenario-dimensions", "source": "scenario_dimensions", "priority": "high"}], "prompt_fragments": {}, "diagram_groups": {}}


def test_service_degrades_cleanly_without_a_model():
    state = {"document_regions": [{"id": "region-1", "text": "设计一款城市医疗用途的飞行汽车"}], "discovery": {"intake": {}, "candidate_sets": [], "coverage": {}, "diagnostics": [], "revision": 0}}
    result = IntelligenceService(pack(), model=None).draft(state)
    assert result["discovery"]["intake"]["system_name"]
    assert result["discovery"]["coverage"]["cells"]
    assert any(item["code"] == "generative_model_unavailable" for item in result["discovery"]["diagnostics"])


def test_service_finalization_requires_individual_review():
    state = {"discovery": {"candidate_sets": [{"lens_id": "risks_questions", "items": [{"id": "risk-1", "element_type": "risk", "status": "candidate", "payload": {"name": "浓雾"}}]}], "accepted_graph": {}, "revision": 1}}
    result = IntelligenceService(pack(), model=None).finalize(state)
    assert result["discovery"]["accepted_graph"]["elements"] == []
    assert result.get("baseline") is None
