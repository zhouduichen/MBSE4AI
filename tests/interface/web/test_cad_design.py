from __future__ import annotations

from fastapi.testclient import TestClient

from rflp_lite.interface.web.app import create_app


def test_cad_design_api_exposes_review_gated_vertical_slice(tmp_path):
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    draft_response = client.post(
        "/projects/p1/cad/intent",
        json={
            "text": "生成铝合金支架，长100毫米，宽50毫米，高10毫米",
            "source_requirement_ids": [],
        },
    )
    assert draft_response.status_code == 200
    draft = draft_response.json()["draft"]
    plan = client.post("/projects/p1/cad/plan", json={"draft_id": draft["draft_id"]}).json()["plan"]
    assert plan["status"] == "ready"
    assert client.post(f"/projects/p1/cad/plans/{plan['id']}/execute").status_code == 422
    assert client.post(f"/projects/p1/cad/plans/{plan['id']}/approve").status_code == 200

    model = client.post(f"/projects/p1/cad/plans/{plan['id']}/execute").json()["model"]
    review = client.post(f"/projects/p1/cad/models/{model['id']}/review").json()["review"]
    assert review["annotations"]
    assert client.post(f"/projects/p1/cad/models/{model['id']}/apply").json()["apply"]["entity"]["kind"] == "physical_block"
    assert client.get("/ui/projects/p1/cad-design").status_code == 200
