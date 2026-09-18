from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from rflp_lite.application.model_generation import build_traceability_summary
from rflp_lite.application.projections.traceability import build_traceability_view
from rflp_lite.application.sysml_v2 import sysml_to_graph
from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.model import AddEntity, Patch, Relate
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.runtime.rule_based import VerticalRuleRuntime


CONCEPT_ROOT = Path("src/rflp_lite/resources/examples/concept-design")


def _services(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("p1", "delivery robot")
    return services


def _services_with_requirement_only(tmp_path: Path):
    services = _services(tmp_path)
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "Battery shall last 8 hours",
        {"statement": "Battery shall last 8 hours"},
    )
    patch = Patch.create("p1", "fixture", (AddEntity(requirement),), "fixture", 0)
    services.repository("p1").append_patch("p1", patch, 0)
    return services


def _services_with_complete_graph(tmp_path: Path):
    services = _services(tmp_path)
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "Battery shall last 8 hours",
        {"statement": "Battery shall last 8 hours"},
        status=EntityStatus.VALIDATED,
    )
    function = make_entity(EntityKind.FUNCTION, "Manage energy", status=EntityStatus.VALIDATED)
    logical = make_entity(EntityKind.LOGICAL_COMPONENT, "Energy controller", status=EntityStatus.VALIDATED)
    physical = make_entity(EntityKind.PHYSICAL_BLOCK, "Battery pack", status=EntityStatus.VALIDATED)
    scope = {
        "requirement_ids": [requirement.id],
        "function_ids": [function.id],
        "logical_component_ids": [logical.id],
        "physical_ids": [physical.id],
    }
    verification = make_entity(
        EntityKind.VERIFICATION_CASE,
        "Endurance test",
        {
            "method": "test",
            "verification_objective": "证明续航需求满足",
            "precondition": "设备完成部署并充满电",
            "test_condition": "额定负载、标准环境和 8 小时边界条件",
            "input": "连续运行任务",
            "stimulus": "启动设备并持续施加运行负载",
            "procedure": "执行连续运行测试并记录剩余电量",
            "expected_result": "设备连续运行达到目标时长",
            "pass_criteria": ">=8h",
            **scope,
        },
        status=EntityStatus.VALIDATED,
    )
    validation = make_entity(
        EntityKind.VALIDATION_CASE,
        "Operational confirmation",
        {
            "method": "demonstration",
            "verification_objective": "确认运营场景目标达成",
            "precondition": "运营人员和典型配送场景可用",
            "test_condition": "真实用户、典型任务和代表性环境",
            "input": "配送任务",
            "stimulus": "运营人员发起并观察一次配送任务",
            "procedure": "在典型场景执行演示并收集确认结果",
            "expected_result": "运营人员确认任务体验满足目标",
            "pass_criteria": "operator confirms",
            **scope,
        },
        status=EntityStatus.VALIDATED,
    )
    relations = (
        Relate(requirement.id, RelationPredicate.SATISFIED_BY, function.id),
        Relate(function.id, RelationPredicate.ALLOCATED_TO, logical.id),
        Relate(logical.id, RelationPredicate.ALLOCATED_TO, physical.id),
        Relate(requirement.id, RelationPredicate.VERIFIED_BY, verification.id),
        Relate(requirement.id, RelationPredicate.VALIDATED_BY, validation.id),
    )
    patch = Patch.create(
        "p1",
        "fixture",
        (
            AddEntity(requirement), AddEntity(function), AddEntity(logical),
            AddEntity(physical), AddEntity(verification), AddEntity(validation),
            *relations,
        ),
        "fixture",
        0,
    )
    services.repository("p1").append_patch("p1", patch, 0)
    return services


def _services_with_safety_pair(tmp_path: Path):
    services = _services(tmp_path)
    first = make_entity(
        EntityKind.FUNCTION,
        "采集任务",
        {"timing_constraints": ["mission-cycle"]},
        status=EntityStatus.VALIDATED,
    )
    second = make_entity(
        EntityKind.FUNCTION,
        "执行任务",
        {"timing_constraints": ["mission-cycle"]},
        status=EntityStatus.VALIDATED,
    )
    safety = {
        "function_ids": [first.id, second.id],
        "must_separate": True,
        "reason": "采集与执行必须隔离",
    }
    first = first.__class__(
        first.meta,
        {**first.payload, "safety_isolation": [safety]},
    )
    logical = make_entity(
        EntityKind.LOGICAL_COMPONENT,
        "任务协调器",
        {"cohesion": "high", "coupling": "controlled"},
        status=EntityStatus.VALIDATED,
    )
    patch = Patch.create(
        "p1",
        "fixture.safety",
        (
            AddEntity(first), AddEntity(second), AddEntity(logical),
            Relate(first.id, RelationPredicate.ALLOCATED_TO, logical.id),
            Relate(second.id, RelationPredicate.ALLOCATED_TO, logical.id),
        ),
        "fixture",
        0,
    )
    services.repository("p1").append_patch("p1", patch, 0)
    return services


def test_build_contains_all_required_artifacts(tmp_path: Path):
    services = _services_with_complete_graph(tmp_path)

    package = services.deliverables("p1").build("p1")

    assert package["format"] == "ai4mbse.engineering-deliverable.v1"
    assert set(package["artifacts"]) == {
        "model", "evidence", "sysml", "requirements", "behavior", "rflp", "rflp_svg", "traceability",
        "vv_plan", "architecture_report",
    }
    assert package["revision"] == package["artifacts"]["traceability"]["content"]["revision"]
    assert package["snapshot_hash"] == package["artifacts"]["rflp"]["content"]["snapshot_hash"]
    assert package["artifacts"]["architecture_report"]["content"]["status"] == "BLOCKED"
    assert package["artifacts"]["vv_plan"]["content"]["metrics"]["requirement_count"] == 1
    assert package["artifacts"]["vv_plan"]["content"]["rows"][0]["test_condition"]
    assert package["artifacts"]["vv_plan"]["content"]["rows"][0]["stimulus"]
    assert package["artifacts"]["evidence"]["content"]["records"] == []
    assert package["artifacts"]["rflp_svg"]["content"].startswith("<svg")


def test_architecture_report_reuses_logical_decision_evidence(tmp_path: Path):
    services = _services_with_safety_pair(tmp_path)

    package = services.deliverables("p1").build("p1")
    report = package["artifacts"]["architecture_report"]["content"]
    logical = report["architecture_synthesis"]["logical"]
    shared = next(
        item for item in logical["candidates"]
        if item["alternative"] == "shared_coordinator"
    )

    assert report["methodology_metrics"]["logical_safety_violation_count"] == 1
    assert report["methodology_metrics"]["logical_safety_review_required"] is True
    assert shared["safety_isolation_count"] == 1
    assert shared["safety_violation_count"] == 1
    archive_bytes, _ = services.deliverables("p1").export_zip("p1")
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        markdown = archive.read("architecture-report.md").decode("utf-8")
    assert "Safety isolation review required" in markdown


def test_traceability_deliverable_matches_canonical_summary_and_projection(tmp_path: Path):
    services = _services_with_complete_graph(tmp_path)
    graph = services.model("p1").graph("p1")
    package = services.deliverables("p1").build("p1")
    trace_rows = package["artifacts"]["traceability"]["content"]["rows"]
    summary = build_traceability_summary(graph)

    assert all(row["coverage_percent"] == 100.0 for row in trace_rows if row["status"] == "PASS")
    assert package["artifacts"]["traceability"]["content"]["revision"] == graph.revision
    assert package["artifacts"]["traceability"]["content"]["rows"] == list(
        build_traceability_view(graph)["rows"]
    )
    assert tuple(summary.paths[0][:4]) == tuple([
        trace_rows[0]["requirement_id"],
        trace_rows[0]["functions"][0],
        trace_rows[0]["logical_components"][0],
        trace_rows[0]["physical_blocks"][0],
    ])


def test_broken_traceability_deliverable_matches_live_projection(tmp_path: Path):
    services = _services_with_requirement_only(tmp_path)
    graph = services.model("p1").graph("p1")
    package = services.deliverables("p1").build("p1")
    live_rows = build_traceability_view(graph)["rows"]
    artifact_rows = package["artifacts"]["traceability"]["content"]["rows"]

    assert [(row["status"], row["gaps"]) for row in artifact_rows] == [
        (row["status"], row["gaps"]) for row in live_rows
    ]


def test_deliverable_snapshots_evidence_without_changing_model_revision(tmp_path: Path):
    services = _services_with_complete_graph(tmp_path)
    repository = services.repository("p1")
    repository.save_evidence(
        "p1",
        {
            "id": "evidence-test",
            "source_type": "test",
            "source_id": "fixture",
            "locator": "case-1",
            "claim": "续航满足要求",
            "excerpt": "实测续航 9 小时",
            "relevance": 1.0,
        },
    )
    revision = services.model("p1").graph("p1").revision

    package = services.deliverables("p1").build("p1")

    evidence = package["artifacts"]["evidence"]["content"]
    assert evidence["revision"] == revision
    assert evidence["records"] == [
        {
            "id": "evidence-test",
            "source_type": "test",
            "source_id": "fixture",
            "locator": "case-1",
            "claim": "续航满足要求",
            "excerpt": "实测续航 9 小时",
            "authority": None,
            "relevance": 1.0,
        }
    ]
    assert package["artifacts"]["model"]["content"]["evidence"] == evidence["records"]
    assert services.model("p1").graph("p1").revision == revision


def test_incomplete_graph_is_reported_as_gap(tmp_path: Path):
    services = _services_with_requirement_only(tmp_path)

    report = services.deliverables("p1").build("p1")["artifacts"]["vv_plan"]["content"]

    assert report["rows"][0]["status"] == "MISSING_VERIFICATION"
    assert report["rows"][0]["missing"] == ["verification"]


def test_zip_is_stable_and_sysml_round_trips(tmp_path: Path):
    services = _services_with_complete_graph(tmp_path)

    first = services.deliverables("p1").export_zip("p1")[0]
    second = services.deliverables("p1").export_zip("p1")[0]

    assert first == second
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        assert set(archive.namelist()) == {
            "manifest.json", "model.json", "evidence.json", "model.sysml", "requirements.json", "behavior.json",
            "rflp.json", "rflp.svg", "traceability.json", "vv-plan.json", "vv-plan.md",
            "architecture-report.json", "architecture-report.md",
        }
        restored = sysml_to_graph(archive.read("model.sysml").decode(), "p1")
    graph = services.model("p1").graph("p1")
    assert {item.id for item in restored.entities} == {item.id for item in graph.entities}
    assert {(item.source_id, item.predicate, item.target_id) for item in restored.relations} == {
        (item.source_id, item.predicate, item.target_id) for item in graph.relations
    }


def test_concept_and_detail_design_records_are_included_in_deliverables(tmp_path: Path):
    services = _services(tmp_path)
    envelope = json.loads((CONCEPT_ROOT / "fixed-wing-envelope.json").read_text(encoding="utf-8"))
    services.concept_design("p1").run(envelope, optimize=False)

    cad = services.cad_design("p1")
    draft = cad.create_intent("生成铝合金支架，长100毫米，宽50毫米，高10毫米")
    plan = cad.create_plan(draft.draft_id)
    cad.approve_plan(plan["id"])
    model = cad.execute_plan(plan["id"])
    review = services.design_review("p1").review(model["id"], model["model_payload"])
    assert review["annotations"]

    package = services.deliverables("p1").build("p1")
    assert {"concept_design", "detail_design"} <= set(package["artifacts"])
    concept_content = package["artifacts"]["concept_design"]["content"]
    assert concept_content["concept_runs"]
    concept_run = concept_content["concept_runs"][-1]
    assert concept_run["evaluation_summary"]["complete_candidate_count"] == concept_run["evaluation_summary"]["candidate_count"]
    assert dict(concept_run["evaluations"][0]["validity"])["validity_status"] == "not_declared"
    assert package["artifacts"]["detail_design"]["content"]["cad_models"]
    assert package["artifacts"]["detail_design"]["content"]["design_reviews"][-1]["artifacts"]["drawing_svg"].startswith("<svg")
    archive_bytes, _ = services.deliverables("p1").export_zip("p1")
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        assert {"concept-design.json", "detail-design.json"} <= set(archive.namelist())
