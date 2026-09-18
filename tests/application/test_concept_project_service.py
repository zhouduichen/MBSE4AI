from __future__ import annotations

import json
from pathlib import Path

from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.domain.entities import EntityKind


ROOT = Path("src/rflp_lite/resources/examples/concept-design")


def test_project_concept_service_generates_and_applies_layout_candidate(tmp_path):
    services = build_v2_services(tmp_path)
    services.projects.create("mission")
    envelope = json.loads((ROOT / "fixed-wing-envelope.json").read_text(encoding="utf-8"))

    result = services.concept_design("mission").run(envelope, optimize=False)

    assert 3 <= len(result.candidates) <= 5
    assert len(result.evaluations) == len(result.candidates) * 3
    applied = services.concept_design("mission").apply_candidate(result.candidates[0].id, result.id)
    assert applied["entity"]["kind"] == EntityKind.PHYSICAL_BLOCK.value
    repeated = services.concept_design("mission").apply_candidate(result.candidates[0].id, result.id)
    assert repeated["idempotent"] is True

    graph = services.repository("mission").load_graph("mission")
    assert any(item.kind is EntityKind.PHYSICAL_BLOCK for item in graph.entities)
    assert services.concept_design("mission").latest().id == result.id
