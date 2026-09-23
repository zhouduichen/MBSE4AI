from __future__ import annotations

import json
from pathlib import Path

import pytest

from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.domain.model import AddEntity, Patch, UpdateEntity
from rflp_lite.evals.acceptance import run_acceptance
from rflp_lite.methodology.contracts import Phase, RunStatus


FIXTURE = Path(__file__).parent / "fixtures" / "campus_delivery_robot.json"


def _seeded_services(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces")
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    services.projects.create("campus", "校园无人配送机器人")
    services.projects.seed_fixture("campus", fixture, source_path=FIXTURE)
    return services, fixture


def test_campus_fixture_runs_all_phases_then_blocks_unreviewed_closure(tmp_path: Path) -> None:
    services, fixture = _seeded_services(tmp_path)

    for phase in (
        Phase.OPERATIONAL,
        Phase.FUNCTIONAL,
        Phase.LOGICAL_PHYSICAL,
        Phase.ASSURANCE,
    ):
        summary = services.analysis("campus").run("campus", phase)
        assert summary.status is RunStatus.COMPLETED
        assert services.analysis("campus").gate("campus", phase).passed

    closure = services.analysis("campus").run("campus", Phase.CLOSURE)
    assert closure.status is RunStatus.BLOCKED
    assert any("requires_human_review" in item for item in closure.diagnostics)
    report = run_acceptance(services.model("campus").graph("campus"), fixture)
    assert report.status == "passed", report.diagnostics

    package = services.deliverables("campus").build("campus")
    graph = services.model("campus").graph("campus")
    assert package["revision"] == graph.revision
    assert package["snapshot_hash"] == graph.snapshot_hash
    trace_metrics = package["artifacts"]["traceability"]["content"]["metrics"]
    assert trace_metrics["requirement_count"] == 7
    assert trace_metrics["complete_count"] == 7
    assert package["artifacts"]["architecture_report"]["content"]["status"] == "PASS"
    vv_rows = package["artifacts"]["vv_plan"]["content"]["rows"]
    assert all(row["status"] == "PASS" for row in vv_rows)
    assert all(row["test_condition"] for row in vv_rows)
    assert all(row["stimulus"] for row in vv_rows)
    assert all(row["execution_status"] == "pending" for row in vv_rows)
    assert all(row["execution_evidence_ids"] == [] for row in vv_rows)


def test_failure_is_registered_and_repaired_with_local_patch(tmp_path: Path) -> None:
    services = build_v2_services(tmp_path / "workspaces")
    services.projects.create("empty")
    result = services.analysis("empty").gate("empty", Phase.OPERATIONAL)
    assert not result.passed
    issue = next(
        item
        for item in services.model("empty").issues("empty")
        if item["code"] == "missing_lifecycle"
    )

    before = services.model("empty").graph("empty").revision
    repaired = services.analysis("empty").repair("empty", str(issue["id"]))
    assert repaired.status is RunStatus.COMPLETED
    assert services.model("empty").graph("empty").revision == before + 1
    assert services.model("empty").entities("empty", EntityKind.LIFECYCLE_STAGE)


def test_locked_entity_rejects_automatic_update(tmp_path: Path) -> None:
    services = build_v2_services(tmp_path / "workspaces")
    services.projects.create("locked")
    repository = services.repository("locked")
    graph = repository.load_graph("locked")
    entity = make_entity(
        EntityKind.REQUIREMENT,
        "不可自动覆盖的需求",
        status=EntityStatus.LOCKED,
        revision=graph.revision,
    )
    repository.append_patch(
        "locked",
        Patch.create("locked", "seed.locked", (AddEntity(entity),), "seed", graph.revision),
        graph.revision,
    )
    current = repository.load_graph("locked")
    patch = Patch.create(
        "locked",
        "automatic.update",
        (UpdateEntity(entity.id, {"name": "被覆盖"}),),
        "should fail",
        current.revision,
    )
    with pytest.raises(ContractViolation):
        repository.append_patch("locked", patch, current.revision)
