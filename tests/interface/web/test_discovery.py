from pathlib import Path

from fastapi.testclient import TestClient

from rflp_lite.application.intelligence.service import IntelligenceService
from rflp_lite.application.mbse_domain_packs import load_mbse_domain_pack
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.interface.web.app import create_app
from rflp_lite.ports.generative_model import GenerationResponse

ROOT = Path(__file__).resolve().parents[3]
PACK_PATH = ROOT / "src" / "rflp_lite" / "resources" / "domain-packs" / "urban-medical-aam-v1.json"

STAKEHOLDER_PAYLOAD = {
    "name": "急救医生",
    "category": "medical",
    "goals": ["稳定患者状态"],
    "interactions": ["提交医疗任务"],
}


class StakeholderModel:
    """Deterministic fake model returning one stakeholder from one lens."""

    def complete_json(self, request):
        item = None
        if request.lens_id == "stakeholders":
            item = {
                "element_type": "stakeholder",
                "payload": STAKEHOLDER_PAYLOAD,
                "source_type": "inferred",
                "source_id": "lens-stakeholders",
                "rationale": "领域分析",
                "confidence": 0.72,
                "assumptions": ["示例假设"],
            }
        payload = {"items": [item] if item else []}
        return GenerationResponse(
            request.lens_id,
            payload,
            canonical_hash(request.user_payload),
            canonical_hash(payload),
            False,
        )


def _client(tmp_path: Path) -> TestClient:
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/workspaces", data={"name": "medical"}, follow_redirects=False).status_code == 303
    response = client.post("/w/medical/requirements/analyze", data={"text": "设计一款城市医疗用途的飞行汽车"}, follow_redirects=False)
    assert response.status_code == 303
    return client


def _client_with_candidates(tmp_path: Path) -> TestClient:
    client = _client(tmp_path)
    facade = client.app.state.facade
    pack = load_mbse_domain_pack(PACK_PATH)
    state = facade.requirements("medical")
    result = IntelligenceService(pack, StakeholderModel()).draft(state)
    facade._save_requirements("medical", result, "discovery.drafted")
    return client


def test_discovery_page_and_local_degraded_run(tmp_path: Path):
    client = _client(tmp_path)
    response = client.get("/w/medical/requirements/discovery")
    assert response.status_code == 200
    assert "智能补全" in response.text
    assert "任务种子" in response.text
    assert "尚未评估覆盖情况" in response.text
    assert "project_llm_unavailable" in response.text
    run = client.post("/api/v1/workspaces/medical/discovery/draft", json={"pack_id": "urban-medical-aam-v1"})
    assert run.status_code == 200
    payload = run.json()
    assert payload["discovery"]["intake"]
    assert any(item["code"] in {"generative_model_unavailable", "generative_model_failed"} for item in payload["discovery"]["diagnostics"])


def test_review_endpoint_requires_current_revision(tmp_path: Path):
    client = _client(tmp_path)
    client.post("/api/v1/workspaces/medical/discovery/draft", json={"pack_id": "urban-medical-aam-v1"})
    response = client.post("/api/v1/workspaces/medical/discovery/review", json={"candidate_id": "candidate-1", "decision": "accepted", "expected_revision": 0, "pack_id": "urban-medical-aam-v1"})
    assert response.status_code == 422


def test_html_page_renders_candidate_review_controls(tmp_path: Path):
    client = _client_with_candidates(tmp_path)
    text = client.get("/w/medical/requirements/discovery").text
    assert "急救医生" in text
    assert "置信度 0.72" in text
    assert "来源：inferred" in text
    assert "示例假设" in text
    assert "接受" in text and "驳回" in text and "编辑" in text and "保存修改" in text
    assert "AI 候选，需人工确认" in text
    assert "lens-stakeholders" in text
    assert "project_llm_unavailable" in text


def test_html_review_finalize_and_diagram_cards(tmp_path: Path):
    client = _client_with_candidates(tmp_path)
    state = client.get("/api/v1/workspaces/medical/requirements").json()["requirements"]
    candidate_id = state["discovery"]["candidate_sets"][0]["items"][0]["id"]
    revision = state["discovery"]["revision"]
    assert client.get("/w/medical/requirements/discovery").text.count("diagram.svg") == 0

    reviewed = client.post(
        "/w/medical/requirements/discovery/review",
        data={"pack_id": "urban-medical-aam-v1", "candidate_id": candidate_id, "decision": "accepted", "expected_revision": str(revision)},
        follow_redirects=False,
    )
    assert reviewed.status_code == 303
    text = client.get("/w/medical/requirements/discovery").text
    assert "1 项已接受" in text
    assert 'class="status-badge accepted"' in text

    finalized = client.post(
        "/w/medical/requirements/discovery/finalize",
        data={"pack_id": "urban-medical-aam-v1"},
        follow_redirects=False,
    )
    assert finalized.status_code == 303
    text = client.get("/w/medical/requirements/discovery").text
    assert "diagram.svg?type=stakeholder_hierarchy" in text
    assert "diagram.svg?type=environment" in text
    assert "diagram.svg?type=traceability" in text

    state = client.get("/api/v1/workspaces/medical/requirements").json()["requirements"]
    assert len(state["discovery"]["accepted_graph"]["elements"]) == 1
    assert any(item["name"] == "急救医生" for item in state["stakeholders"])

    svg = client.get("/w/medical/requirements/discovery/diagram.svg", params={"type": "environment"})
    assert svg.status_code == 200
    assert svg.headers["content-type"].startswith("image/svg+xml")
    assert b"<svg" in svg.content
    assert b"data-source-id=" in svg.content


def test_html_review_rejects_stale_revision(tmp_path: Path):
    client = _client_with_candidates(tmp_path)
    state = client.get("/api/v1/workspaces/medical/requirements").json()["requirements"]
    candidate_id = state["discovery"]["candidate_sets"][0]["items"][0]["id"]
    response = client.post(
        "/w/medical/requirements/discovery/review",
        data={"pack_id": "urban-medical-aam-v1", "candidate_id": candidate_id, "decision": "accepted", "expected_revision": "0"},
    )
    assert response.status_code == 422


def test_html_edit_updates_candidate_name(tmp_path: Path):
    client = _client_with_candidates(tmp_path)
    state = client.get("/api/v1/workspaces/medical/requirements").json()["requirements"]
    group = state["discovery"]["candidate_sets"][0]
    candidate = group["items"][0]
    revision = state["discovery"]["revision"]
    payload = dict(candidate["payload"])

    edited = client.post(
        "/w/medical/requirements/discovery/edit",
        data={
            "pack_id": "urban-medical-aam-v1",
            "candidate_id": candidate["id"],
            "expected_revision": str(revision),
            "payload": __import__("json").dumps(payload),
            "name": "急诊医生",
        },
        follow_redirects=False,
    )
    assert edited.status_code == 303
    state = client.get("/api/v1/workspaces/medical/requirements").json()["requirements"]
    item = state["discovery"]["candidate_sets"][0]["items"][0]
    assert item["payload"]["name"] == "急诊医生"
    assert item["status"] == "accepted"
