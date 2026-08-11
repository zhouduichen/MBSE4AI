import json
from copy import deepcopy
from pathlib import Path

from rflp_lite.adapters.deterministic_svg_renderer import DeterministicSvgRenderer
from rflp_lite.application.diagrams.service import DiagramService
from rflp_lite.application.intelligence.service import IntelligenceService
from rflp_lite.application.mbse_domain_packs import load_mbse_domain_pack, validate_candidate_payload
from rflp_lite.application.workbench_schema import migrate_workbench_state
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.ports.generative_model import GenerationResponse


ROOT = Path("src/rflp_lite/resources/examples/discovery")
PACK_PATH = Path("src/rflp_lite/resources/domain-packs/urban-medical-aam-v1.json")


class FixtureModel:
    def __init__(self, responses):
        self.responses = responses

    def complete_json(self, request):
        payload = self.responses.get(request.lens_id, {"items": []})
        return GenerationResponse(request.lens_id, payload, canonical_hash(request.user_payload), canonical_hash(payload), False)


def build_fixture_run():
    state = migrate_workbench_state({"document_regions": [{"id": "region-1", "text": (ROOT / "urban-medical-aam-seed.txt").read_text(encoding="utf-8")}], "discovery": {"intake": {}, "candidate_sets": [], "coverage": {}, "diagnostics": [], "revision": 0}})
    pack = load_mbse_domain_pack(PACK_PATH)
    responses = json.loads((ROOT / "urban-medical-aam-model-responses.json").read_text(encoding="utf-8"))
    return state, pack, FixtureModel(responses)


def test_sparse_urban_medical_aam_reaches_reviewed_graph_and_diagrams():
    state, pack, model = build_fixture_run()
    service = IntelligenceService(pack, model)
    draft = service.draft(state)
    assert draft["discovery"]["intake"]["system_name"] == "城市医疗用途的飞行汽车"
    assert all(item["status"] == "candidate" for group in draft["discovery"]["candidate_sets"] for item in group["items"])
    reviewed = draft
    for group in list(reviewed["discovery"]["candidate_sets"]):
        for item in list(group["items"]):
            reviewed = service.review(reviewed, item["id"], "accepted", reviewed["discovery"]["revision"])
    finalized = service.finalize(reviewed)
    graph = finalized["discovery"]["accepted_graph"]
    assert graph["elements"] and graph["relations"]
    assert finalized.get("baseline") is None
    rendered = DiagramService(DeterministicSvgRenderer()).render_all(graph, pack)
    assert rendered and all(b"<svg" in item.content and b"data-source-id=" in item.content for item in rendered)


def test_every_required_coverage_cell_is_assessed():
    state, pack, model = build_fixture_run()
    cells = IntelligenceService(pack, model).draft(state)["discovery"]["coverage"]["cells"]
    assert cells and all(cell["status"] in {"covered", "candidate", "unknown", "not_applicable"} for cell in cells)


def test_pack_can_add_optional_stakeholder_field_without_python_change():
    _state, pack, _model = build_fixture_run()
    extended = deepcopy(pack)
    schema = extended["element_schemas"]["stakeholder"]
    schema.setdefault("properties", {})["flight_zone"] = {"type": "string"}
    payload = validate_candidate_payload(extended, "stakeholder", {"name": "起降场运营方", "category": "vertiport", "goals": ["保障周转"], "interactions": ["分配起降位"], "flight_zone": "urban-core"})
    assert payload["flight_zone"] == "urban-core"


def test_v2_migration_preserves_existing_mbse():
    state = migrate_workbench_state({"schema_version": 2, "mbse": {"revision": "old"}})
    assert state["mbse"] == {"revision": "old"}
    assert state["schema_version"] == 3
