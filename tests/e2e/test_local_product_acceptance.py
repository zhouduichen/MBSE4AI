from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from rflp_lite.application.sysml_v2 import graph_to_sysml, sysml_to_graph
from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.model import Patch, UpdateEntity
from rflp_lite.runtime.rule_based import VerticalRuleRuntime


CONCEPT_ROOT = Path("src/rflp_lite/resources/examples/concept-design")
SOURCE = Path("tests/fixtures/requirements_use_case_acceptance.txt")


def test_local_product_chain_from_document_to_engineering_package(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("acceptance", "本地完整产品验收")
    ingested = services.projects.ingest("acceptance", SOURCE)

    result = services.generation("acceptance").generate("acceptance")
    graph = services.model("acceptance").graph("acceptance")
    requirements = [item for item in graph.entities if item.kind is EntityKind.REQUIREMENT]
    assert len(requirements) == 4
    assert any(item.kind is EntityKind.USE_CASE for item in graph.entities)
    assert any(item.kind is EntityKind.OPERATIONAL_SCENARIO for item in graph.entities)
    assert any(item.kind is EntityKind.ACTIVITY for item in graph.entities)
    assert any(
        event.get("kind") == "model_generation.input_intake"
        for event in services.repository("acceptance").list_audit_events("acceptance")
    )
    assert result.status == "completed"
    assert result.traceability.complete_count == len(requirements)
    assert [stage.stage for stage in result.stage_results] == [
        "requirements", "functional", "logical", "physical", "verification_validation",
    ]
    assert ingested["document_id"]

    sysml = graph_to_sysml(graph)
    restored = sysml_to_graph(sysml, "acceptance")
    assert {item.id for item in restored.entities} == {item.id for item in graph.entities}
    assert {(item.source_id, item.predicate, item.target_id) for item in restored.relations} == {
        (item.source_id, item.predicate, item.target_id) for item in graph.relations
    }
    function = next(item for item in requirements if item.kind is EntityKind.REQUIREMENT)
    services.model("acceptance").apply_patch(
        "acceptance",
        Patch.create(
            "acceptance",
            "local.acceptance.edit",
            (UpdateEntity(function.id, {"payload": {"review_note": "人工确认后继续"}}),),
            "本地验收编辑模型",
            graph.revision,
        ),
        graph.revision,
    )

    envelope = json.loads((CONCEPT_ROOT / "fixed-wing-envelope.json").read_text(encoding="utf-8"))
    envelope["source_requirement_ids"] = []
    concept = services.concept_design("acceptance").run(envelope, optimize=False)
    assert 3 <= len(concept.candidates) <= 5
    assert len(concept.evaluations) == len(concept.candidates) * 3
    assert concept.envelope.source_requirement_ids == tuple(item.id for item in requirements)

    cad = services.cad_design("acceptance")
    draft = cad.create_intent(
        "生成铝合金支架，长100毫米，宽50毫米，高10毫米",
    )
    assert draft.intent.source_requirement_ids == tuple(item.id for item in requirements)
    plan = cad.create_plan(draft.draft_id)
    assert plan["status"] == "ready"
    assert plan["preview"]["schema_version"] == "parametric-cad-preview.v1"
    cad.approve_plan(plan["id"])
    model = cad.execute_plan(plan["id"])
    review = services.design_review("acceptance").review(model["id"], model["model_payload"])
    assert review["annotations"]
    assert review["artifacts"]["risk_highlight_svg"].startswith("<svg")

    risky_payload = json.loads(json.dumps(model["model_payload"]))
    risky_payload["parts"][0]["features"].append({
        "id": "acceptance-risk",
        "kind": "add_hole",
        "parameters": {"diameter_mm": 10, "edge_distance_mm": 5, "tool_access": False},
    })
    risky_review = services.design_review("acceptance").review("acceptance-risk-model", risky_payload)
    assert risky_review["status"] == "needs_review"
    assert {item["rule_id"] for item in risky_review["findings"]} >= {
        "dfm.hole_edge_distance", "dfa.tool_access",
    }

    applied = cad.apply_model(model["id"])
    assert applied["entity"]["kind"] == EntityKind.PHYSICAL_BLOCK.value
    assert applied["entity"]["payload"]["design_review"]["id"] == review["id"]
    assert applied["entity"]["payload"]["design_review"]["annotations"] == review["annotations"]
    detail_graph = services.model("acceptance").graph("acceptance")
    detail_restored = sysml_to_graph(graph_to_sysml(detail_graph), "acceptance")
    restored_physical = next(
        item for item in detail_restored.entities
        if item.id == applied["entity"]["id"]
    )
    assert restored_physical.payload["design_review"]["findings"] == review["findings"]
    package = services.deliverables("acceptance").build("acceptance")
    assert {"sysml", "behavior", "traceability", "concept_design", "detail_design"} <= set(package["artifacts"])
    assert package["artifacts"]["behavior"]["content"]["sequence_diagrams"]
    archive_bytes, _ = services.deliverables("acceptance").export_zip("acceptance")
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        assert {"model.sysml", "behavior.json", "concept-design.json", "detail-design.json"} <= set(archive.namelist())
