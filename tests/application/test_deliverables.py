from __future__ import annotations

import io
import zipfile
from pathlib import Path

from rflp_lite.application.sysml_v2 import sysml_to_graph
from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import AddEntity, Patch, Relate
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.runtime.rule_based import VerticalRuleRuntime


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
    )
    function = make_entity(EntityKind.FUNCTION, "Manage energy")
    logical = make_entity(EntityKind.LOGICAL_COMPONENT, "Energy controller")
    physical = make_entity(EntityKind.PHYSICAL_BLOCK, "Battery pack")
    verification = make_entity(
        EntityKind.VERIFICATION_CASE,
        "Endurance test",
        {"method": "test", "pass_criteria": ">=8h"},
    )
    validation = make_entity(
        EntityKind.VALIDATION_CASE,
        "Operational confirmation",
        {"method": "demonstration", "pass_criteria": "operator confirms"},
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


def test_build_contains_all_required_artifacts(tmp_path: Path):
    services = _services_with_complete_graph(tmp_path)

    package = services.deliverables("p1").build("p1")

    assert package["format"] == "ai4mbse.engineering-deliverable.v1"
    assert set(package["artifacts"]) == {
        "model", "sysml", "requirements", "rflp", "traceability",
        "vv_plan", "architecture_report",
    }
    assert package["revision"] == package["artifacts"]["traceability"]["content"]["revision"]
    assert package["snapshot_hash"] == package["artifacts"]["rflp"]["content"]["snapshot_hash"]
    assert package["artifacts"]["architecture_report"]["content"]["status"] == "BLOCKED"


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
            "manifest.json", "model.json", "model.sysml", "requirements.json",
            "rflp.json", "traceability.json", "vv-plan.json", "vv-plan.md",
            "architecture-report.json", "architecture-report.md",
        }
        restored = sysml_to_graph(archive.read("model.sysml").decode(), "p1")
    graph = services.model("p1").graph("p1")
    assert {item.id for item in restored.entities} == {item.id for item in graph.entities}
    assert {(item.source_id, item.predicate, item.target_id) for item in restored.relations} == {
        (item.source_id, item.predicate, item.target_id) for item in graph.relations
    }
