from rflp_lite.application.intelligence.coverage import evaluate_coverage, fill_high_priority_gaps
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.ports.generative_model import GenerationResponse


PACK = {"id": "urban-medical-aam-v1", "stakeholder_lenses": [{"id": "medical", "label": "医疗"}, {"id": "regulatory", "label": "监管"}], "lifecycle_phases": [{"id": "takeoff", "label": "起飞"}], "scenario_dimensions": [{"id": "weather", "label": "天气", "values": ["rain", "fog"]}], "coverage_rules": [{"id": "stakeholder-lenses", "source": "stakeholder_lenses", "priority": "high"}, {"id": "lifecycle-phases", "source": "lifecycle_phases", "priority": "high"}, {"id": "scenario-dimensions", "source": "scenario_dimensions", "priority": "high"}], "element_schemas": {"stakeholder": {"required": ["name", "category", "goals", "interactions"]}}}


def test_coverage_assigns_every_cell_a_known_status():
    state = {"discovery": {"candidate_sets": [{"lens_id": "stakeholders", "items": [{"id": "c1", "element_type": "stakeholder", "status": "candidate", "payload": {"name": "医生", "category": "medical", "goals": ["救治"], "interactions": ["下达任务"]}}]}], "coverage": {}, "revision": 1}}
    result = evaluate_coverage(state, PACK)
    cells = result["discovery"]["coverage"]["cells"]
    assert cells and {cell["status"] for cell in cells} <= {"covered", "candidate", "unknown", "not_applicable"}
    assert any(cell["key"] == "stakeholder-lenses/regulatory" and cell["status"] == "unknown" for cell in cells)


def test_gap_fill_calls_model_once_and_marks_attempt():
    class GapModel:
        def __init__(self): self.calls = 0
        def complete_json(self, request):
            self.calls += 1
            payload = {"items": []}
            return GenerationResponse(request.lens_id, payload, canonical_hash(request.user_payload), canonical_hash(payload), False)
    state = evaluate_coverage({"discovery": {"candidate_sets": [], "coverage": {}, "revision": 1}}, PACK)
    model = GapModel()
    first = fill_high_priority_gaps(state, PACK, model)
    second = fill_high_priority_gaps(first, PACK, model)
    assert model.calls == 1
    assert second["discovery"]["coverage"]["gap_fill_attempted"] is True
