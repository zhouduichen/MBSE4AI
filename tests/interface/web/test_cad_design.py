from __future__ import annotations

from fastapi.testclient import TestClient

from rflp_lite.interface.web.app import create_app


def test_cad_design_api_exposes_review_gated_vertical_slice(tmp_path):
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    requirement = client.post(
        "/projects/p1/requirements",
        json={"text": "系统应支持详细结构设计"},
    ).json()["requirement"]

    draft_response = client.post(
        "/projects/p1/cad/intent",
        json={
            "text": "生成铝合金支架，长100毫米，宽50毫米，高10毫米",
            "source_requirement_ids": [],
        },
    )
    assert draft_response.status_code == 200
    draft = draft_response.json()["draft"]
    assert draft["source_requirement_ids"] == [requirement["id"]]
    assert len(draft["structure_options"]) >= 2
    selected = draft["structure_options"][0]["id"]
    plan = client.post(
        "/projects/p1/cad/plan",
        json={"draft_id": draft["draft_id"], "selected_structure_option_id": selected},
    ).json()["plan"]
    assert plan["status"] == "ready"
    assert plan["selected_structure_option_id"] == selected
    assert client.post(f"/projects/p1/cad/plans/{plan['id']}/execute").status_code == 422
    assert client.post(f"/projects/p1/cad/plans/{plan['id']}/approve").status_code == 200

    model = client.post(f"/projects/p1/cad/plans/{plan['id']}/execute").json()["model"]
    review = client.post(f"/projects/p1/cad/models/{model['id']}/review").json()["review"]
    assert review["annotations"]
    assert review["artifacts"]["drawing_svg"].startswith("<svg")
    assert review["artifacts"]["drawing_hash"]
    assert review["artifacts"]["risk_highlight_svg"].startswith("<svg")
    listed_reviews = client.get("/projects/p1/cad/reviews")
    assert listed_reviews.status_code == 200
    assert listed_reviews.json()["reviews"][-1]["id"] == review["id"]
    applied = client.post(f"/projects/p1/cad/models/{model['id']}/apply").json()["apply"]
    assert applied["entity"]["kind"] == "physical_block"
    assert applied["entity"]["payload"]["design_review"]["id"] == review["id"]
    page = client.get("/ui/projects/p1/cad-design")
    assert page.status_code == 200
    assert "结构选型推荐" in page.text
    assert "审查记录与风险高亮" in page.text
    assert "风险高亮" in page.text
    assert review["id"] in page.text
