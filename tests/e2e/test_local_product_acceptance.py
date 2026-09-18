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
CONCEPT_SOURCE = Path("tests/fixtures/fixed_wing_concept_acceptance.txt")


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
    original_cases = {
        item.id: item.payload.get("branch_scenarios")
        for item in graph.entities
        if item.kind in {EntityKind.VERIFICATION_CASE, EntityKind.VALIDATION_CASE}
    }
    restored_cases = {
        item.id: item.payload.get("branch_scenarios")
        for item in restored.entities
        if item.kind in {EntityKind.VERIFICATION_CASE, EntityKind.VALIDATION_CASE}
    }
    assert restored_cases == original_cases
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
    assert concept.evaluation_summary["complete_candidate_count"] == len(concept.candidates)
    assert dict(concept.evaluations[0].validity)["approval_record"] == "missing"
    assert concept.envelope.source_requirement_ids == tuple(item.id for item in requirements)

    cad = services.cad_design("acceptance")
    draft = cad.create_intent(
        "生成铝合金支架，长100毫米，宽50毫米，高10毫米",
    )
    assert draft.intent.source_requirement_ids == tuple(item.id for item in requirements)
    selected = draft.payload["structure_options"][0]["id"]
    plan = cad.create_plan(draft.draft_id, selected_structure_option_id=selected)
    assert plan["status"] == "ready"
    assert plan["selected_structure_option_id"] == selected
    assert [item["operation"] for item in plan["operations"]].count("add_rib") == 2
    assert plan["preview"]["schema_version"] == "parametric-cad-preview.v1"
    cad.approve_plan(plan["id"])
    model = cad.execute_plan(plan["id"])
    assert [item["kind"] for item in model["model_payload"]["parts"][0]["features"]][-2:] == ["add_rib", "add_rib"]
    review = services.design_review("acceptance").review(model["id"], model["model_payload"])
    assert review["annotations"]
    assert review["artifacts"]["drawing_svg"].startswith("<svg")
    assert review["artifacts"]["drawing_hash"]
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
    assert applied["entity"]["payload"]["selected_structure_option_id"] == selected
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
    assert package["artifacts"]["detail_design"]["content"]["design_reviews"][-1]["artifacts"]["drawing_svg"].startswith("<svg")
    assert [
        item["operation"]
        for item in package["artifacts"]["detail_design"]["content"]["cad_execution_plans"][-1]["operations"]
    ].count("add_rib") == 2
    archive_bytes, _ = services.deliverables("acceptance").export_zip("acceptance")
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        assert {"model.sysml", "behavior.json", "concept-design.json", "detail-design.json"} <= set(archive.namelist())


def test_document_requirements_drive_concept_layout_without_example_defaults(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("fixed-wing", "固定翼需求驱动总体设计")
    ingested = services.projects.ingest("fixed-wing", CONCEPT_SOURCE)

    generated = services.generation("fixed-wing").generate("fixed-wing")
    suggestion = services.concept_design("fixed-wing").suggest_input()

    assert ingested["document_id"]
    assert generated.status == "completed"
    assert suggestion["status"] == "ready"
    assert suggestion["missing_parameters"] == []
    assert suggestion["envelope"]["parameters"]["mass_kg"] == 560.0
    assert len(suggestion["evidence"]) == 9

    result = services.concept_design("fixed-wing").run(
        suggestion["envelope"],
        optimize=False,
    )

    assert 3 <= len(result.candidates) <= 5
    assert len(result.evaluations) == len(result.candidates) * 3
    applied = services.concept_design("fixed-wing").apply_candidate(
        result.candidates[0].id,
        result.id,
    )
    assert applied["entity"]["payload"]["source_requirement_ids"] == suggestion["source_requirement_ids"]


def test_unified_product_flow_binds_document_model_sysml_and_deliverable(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("flow", "统一产品流验收")
    ingested = services.projects.ingest("flow", SOURCE)

    result = services.product_flow("flow").run(
        "flow",
        document_ids=(ingested["document_id"],),
    )

    assert result.status == "completed"
    package = result.deliverable
    assert package["revision"] == result.revision
    assert package["snapshot_hash"] == result.snapshot_hash
    assert package["artifacts"]["sysml"]["content"].startswith("package")
    requirement_rows = package["artifacts"]["requirements"]["content"]["rows"]
    assert len(requirement_rows) == 4
    assert all(item["source_count"] for item in requirement_rows)
    assert package["artifacts"]["traceability"]["content"]["metrics"]["complete_count"] == 4
    assert all(
        entity.meta.source_ids and entity.meta.evidence_ids
        for entity in services.model("flow").graph("flow").entities
        if entity.kind is EntityKind.REQUIREMENT
    )


def test_unified_product_flow_carries_concept_and_cad_to_reviewed_delivery(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("full-flow", "统一设计链验收")
    ingested = services.projects.ingest("full-flow", CONCEPT_SOURCE)

    result = services.product_flow("full-flow").run(
        "full-flow",
        document_ids=(ingested["document_id"],),
        include_concept=True,
        optimize_concept=True,
        cad_intent_text="生成铝合金支架，长100毫米，宽50毫米，高10毫米",
        selected_structure_option_id="bracket-gusseted-plate",
    )

    assert result.status == "needs_approval"
    assert result.concept["status"] == "completed"
    concept_run = result.concept["run"]
    assert 3 <= len(concept_run["optimization"]["iteration_records"][0][1]["candidate_ids"]) <= 5
    assert len(concept_run["candidates"]) > len(concept_run["optimization"]["iteration_records"][0][1]["candidate_ids"])
    assert len(concept_run["evaluations"]) == 24
    assert len(concept_run["optimization"]["iteration_records"]) == 2
    assert concept_run["optimization"]["stop_reason"] == "evaluation_budget"
    assert concept_run["evaluation_summary"]["optimization_evidence_status"] == "development"
    assert result.cad["status"] == "needs_approval"
    assert result.cad["plan"]["selected_structure_option_id"] == "bracket-gusseted-plate"
    assert [item["operation"] for item in result.cad["plan"]["operations"]].count("add_rib") == 2
    assert {"concept_design", "detail_design"} <= set(result.deliverable["artifacts"])

    cad = services.cad_design("full-flow")
    cad.approve_plan(result.cad["plan"]["id"])
    model = cad.execute_plan(result.cad["plan"]["id"])
    review = services.design_review("full-flow").review(model["id"], model["model_payload"])
    applied = cad.apply_model(model["id"])
    final_package = services.deliverables("full-flow").build("full-flow")

    assert review["annotations"]
    assert review["artifacts"]["drawing_hash"]
    assert applied["entity"]["kind"] == EntityKind.PHYSICAL_BLOCK.value
    assert final_package["revision"] == services.model("full-flow").graph("full-flow").revision
    assert final_package["artifacts"]["detail_design"]["content"]["design_reviews"][-1]["id"] == review["id"]


def test_concept_layout_context_flows_into_cad_intent_and_modelgraph(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("handoff", "概念布局到详细设计上下文验收")
    services.projects.ingest("handoff", CONCEPT_SOURCE)
    services.generation("handoff").generate("handoff")

    suggestion = services.concept_design("handoff").suggest_input()
    concept = services.concept_design("handoff").run(
        suggestion["envelope"],
        optimize=False,
    )
    concept_applied = services.concept_design("handoff").apply_candidate(
        concept.candidates[0].id,
        concept.id,
    )
    concept_entity_id = concept_applied["entity"]["id"]

    cad = services.cad_design("handoff")
    draft = cad.create_intent("生成铝合金支架，长100毫米，宽50毫米，高10毫米")
    assert draft.intent.context_model_ids == (concept_entity_id,)

    plan = cad.create_plan(draft.draft_id)
    assert plan["model_context_ids"] == [concept_entity_id]
    cad.approve_plan(plan["id"])
    model = cad.execute_plan(plan["id"])
    review = services.design_review("handoff").review(model["id"], model["model_payload"])
    applied = cad.apply_model(model["id"])

    assert applied["entity"]["payload"]["context_model_ids"] == [concept_entity_id]
    assert applied["entity"]["payload"]["design_intent"]["context_model_ids"] == [concept_entity_id]
    assert review["annotations"]
    assert review["artifacts"]["risk_highlight_svg"].startswith("<svg")


def test_local_cad_profiles_reach_modelgraph_and_review(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("profiles", "通用 CAD profile 验收")
    cad = services.cad_design("profiles")

    requests = (
        ("壳体", "生成铝合金壳体，长120毫米，宽80毫米，高60毫米，壁厚2毫米", "create_shell"),
        ("阶梯轴", "生成阶梯轴，直径20毫米，长度100毫米，阶梯直径14毫米，阶梯长度30毫米", "add_shaft_step"),
        ("齿轮", "生成钢制齿轮，模数2，齿数20，齿宽12毫米，孔径8毫米", "create_gear"),
    )
    applied_ids = []
    for name, statement, expected_operation in requests:
        draft = cad.create_intent(statement)
        plan = cad.create_plan(draft.draft_id)
        assert plan["status"] == "ready", name
        assert expected_operation in {item["operation"] for item in plan["operations"]}
        cad.approve_plan(plan["id"])
        model = cad.execute_plan(plan["id"])
        review = services.design_review("profiles").review(model["id"], model["model_payload"])
        assert review["annotations"]
        applied = cad.apply_model(model["id"])
        applied_ids.append(applied["entity"]["id"])
        assert applied["entity"]["payload"]["cad_model_payload"]["parts"]

    graph = services.model("profiles").graph("profiles")
    assert set(applied_ids) <= set(graph.entity_index)
    assert len([item for item in graph.entities if item.kind is EntityKind.PHYSICAL_BLOCK]) >= 3


def test_local_design_review_rule_context_is_delivered_with_model_evidence(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("review-context", "规则上下文验收")
    review = services.design_review("review-context").review(
        "housing-review",
        {
            "design_review_context": {
                "rule_set": "cnc_machined",
                "assembly_interfaces": [{
                    "part_id": "housing",
                    "feature_id": "mounting-hole-1",
                    "interface": "mounting",
                    "required": True,
                }],
            },
            "parts": [{
                "id": "housing",
                "material": "铝合金",
                "bbox_mm": [120, 80, 60],
                "features": [{
                    "id": "shell",
                    "kind": "create_shell",
                    "parameters": {"wall_thickness_mm": 1.5},
                }],
            }],
        },
    )

    assert review["status"] == "needs_review"
    assert review["artifacts"]["rule_set"] == "cnc_machined"
    assert review["artifacts"]["finding_summary"]["total"] >= 2
    assert review["artifacts"]["evidence_hash"]
    assert review["artifacts"]["risk_highlight_svg"].startswith("<svg")
