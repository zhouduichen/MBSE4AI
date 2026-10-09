from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.interface.web.app import create_app


@pytest.mark.skipif(
    os.getenv("AI4MBSE_CAD_BACKEND", "").casefold() != "freecad-remote",
    reason="remote FreeCAD acceptance test is opt-in",
)
def test_remote_freecad_generates_reloads_reviews_and_applies_model(tmp_path: Path):
    services = build_v2_services(tmp_path)
    services.projects.create("p")
    cad = services.cad_design("p")

    draft = cad.create_intent("生成铝合金支架，长100毫米，宽50毫米，高10毫米，孔径10毫米")
    plan = cad.create_plan(draft.draft_id)
    assert plan["capabilities"]["cad_system"] == "FreeCAD"
    assert plan["preview"]["schema_version"] == "freecad-cad-model.v1"

    cad.approve_plan(plan["id"])
    model = cad.execute_plan(plan["id"])
    payload = model["model_payload"]
    assert payload["source_kind"] == "real"
    assert payload["reload_verification"]["fcstd_readable"] is True
    assert payload["reload_verification"]["shape_valid"] is True
    assert payload["parts"][0]["volume_mm3"] > 0
    assert Path(payload["artifacts"]["fcstd"]).is_file()
    assert Path(payload["artifacts"]["step"]).is_file()

    review = services.design_review("p").review(model["id"], payload)
    assert review["source_kind"] == "real"
    assert review["artifacts"]["risk_highlight_svg"].startswith("<svg")
    assert review["rule_version"] == "dfm-dfa-freecad-1.0"

    applied = cad.apply_model(model["id"])
    assert applied["entity"]["kind"] == "physical_block"

    with TestClient(create_app(tmp_path)) as client:
        download = client.get(f"/projects/p/cad/models/{model['id']}/artifacts/fcstd")
    assert download.status_code == 200
    assert download.content[:2] == b"PK"
