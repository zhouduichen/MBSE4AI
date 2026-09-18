from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from rflp_lite.interface.web.app import create_app


ROOT = Path("src/rflp_lite/resources/examples/concept-design")


def test_concept_design_api_generates_evaluates_and_applies(tmp_path):
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    requirement = client.post(
        "/projects/p1/requirements",
        json={"text": "系统应满足总体布局约束"},
    ).json()["requirement"]
    envelope = json.loads((ROOT / "fixed-wing-envelope.json").read_text(encoding="utf-8"))
    envelope["source_requirement_ids"] = []

    response = client.post(
        "/projects/p1/concept-design/run",
        json={"envelope": envelope, "optimize": False},
    )
    assert response.status_code == 200
    run = response.json()["run"]
    assert 3 <= len(run["candidates"]) <= 5
    assert len(run["evaluations"]) == len(run["candidates"]) * 3
    assert run["formal_status"] == "development"
    assert run["envelope"]["source_requirement_ids"] == [requirement["id"]]

    applied = client.post(
        f"/projects/p1/concept-design/{run['id']}/apply",
        json={"candidate_id": run["candidates"][0]["id"]},
    )
    assert applied.status_code == 200
    assert applied.json()["apply"]["entity"]["kind"] == "physical_block"
    assert applied.json()["apply"]["entity"]["payload"]["source_requirement_ids"] == [requirement["id"]]
    page = client.get("/ui/projects/p1/concept-design")
    assert page.status_code == 200
    assert "多学科评估" in page.text
    assert "优化反馈" in page.text
    assert "Pareto" in page.text


def test_concept_design_input_advisor_projects_requirement_constraints(tmp_path):
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    requirement = client.post(
        "/projects/p1/requirements",
        json={"text": "最大起飞重量不得超过 600 kg"},
    ).json()["requirement"]

    response = client.get("/projects/p1/concept-design/input")

    assert response.status_code == 200
    suggestion = response.json()["input"]
    assert suggestion["source_requirement_ids"] == [requirement["id"]]
    assert suggestion["inferred_bounds"]["mass_kg"]["maximum"] == 600.0
    assert suggestion["missing_parameters"]
    assert suggestion["evidence"][0]["requirement_id"] == requirement["id"]
    assert "从 ModelGraph 提取指标" in client.get("/ui/projects/p1/concept-design").text
