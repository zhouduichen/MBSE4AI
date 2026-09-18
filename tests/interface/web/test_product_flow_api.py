from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from rflp_lite.interface.web.app import create_app
from rflp_lite.runtime.rule_based import VerticalRuleRuntime


def _client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path / "workspaces")
    app.state.container.v2._runtime_override = VerticalRuleRuntime()
    return TestClient(app)


def test_product_flow_api_returns_document_backed_complete_flow(tmp_path: Path):
    client = _client(tmp_path)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    source = Path(__file__).parents[2] / "fixtures" / "requirements_use_case_acceptance.txt"
    uploaded = client.post(
        "/projects/p1/documents",
        files={"file": (source.name, source.read_bytes(), "text/plain")},
    )
    document_id = uploaded.json()["document"]["document_id"]

    response = client.post(
        "/projects/p1/engineering-flow",
        json={"document_ids": [document_id]},
    )

    assert response.status_code == 200
    flow = response.json()["flow"]
    assert flow["status"] == "completed"
    assert flow["generation"]["traceability"]["end_to_end_complete_count"] == 4
    assert flow["revision"] == flow["deliverable"]["revision"]
    assert flow["snapshot_hash"] == flow["deliverable"]["snapshot_hash"]


def test_product_flow_api_returns_review_boundary_states(tmp_path: Path):
    client = _client(tmp_path)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    clarification = client.post(
        "/projects/p1/engineering-flow",
        json={
            "requirement_text": "系统应支持详细结构设计",
            "cad_intent_text": "生成一个零件",
        },
    )
    assert clarification.status_code == 200
    assert clarification.json()["flow"]["status"] == "needs_clarification"

    approval = client.post(
        "/projects/p1/engineering-flow",
        json={
            "requirement_text": "系统应支持详细结构设计",
            "cad_intent_text": "生成铝合金支架，长100毫米，宽50毫米，高10毫米",
        },
    )
    assert approval.status_code == 200
    flow = approval.json()["flow"]
    assert flow["status"] == "needs_approval"
    assert flow["cad"]["plan"]["approval_status"] == "pending"


def test_product_flow_api_returns_concept_input_boundary(tmp_path: Path):
    client = _client(tmp_path)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    response = client.post(
        "/projects/p1/engineering-flow",
        json={
            "requirement_text": "系统应满足总体布局约束",
            "include_concept": True,
            "optimize_concept": False,
        },
    )

    assert response.status_code == 200
    flow = response.json()["flow"]
    assert flow["status"] == "needs_input"
    assert flow["concept"]["status"] == "needs_input"

