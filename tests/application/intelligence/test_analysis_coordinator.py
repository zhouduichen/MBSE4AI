from __future__ import annotations

import time
from pathlib import Path

from rflp_lite.application.intelligence.analysis_coordinator import AnalysisCoordinator
from rflp_lite.application.intelligence.enrichment_jobs import EnrichmentJobRunner
from rflp_lite.application.web_facade import WebFacade
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import AdapterFailure
from rflp_lite.ports.generative_model import GenerationResponse


class OrderedModel:
    model_id = "ordered-test"

    def __init__(self, failing: str | None = None) -> None:
        self.calls: list[str] = []
        self.failing = failing

    def complete_json(self, request):
        block_id = str(request.user_payload["block_id"])
        self.calls.append(block_id)
        if block_id == self.failing:
            raise AdapterFailure(f"{block_id} failed")
        payload = {"items": [], "diagnostics": []}
        return GenerationResponse(
            request.lens_id,
            payload,
            canonical_hash(request.user_payload),
            canonical_hash(payload),
            False,
            provider_id="test",
            model_id=self.model_id,
        )


def _runner(tmp_path: Path) -> EnrichmentJobRunner:
    facade = WebFacade(tmp_path / "workspaces")
    facade.create_workspace("demo")
    facade.analyze_requirements("demo", "requirements.txt", "系统应支持备份。".encode())
    return EnrichmentJobRunner(facade.workspace("demo").path)


def _wait(runner: EnrichmentJobRunner, job_id: str) -> dict[str, object]:
    for _ in range(200):
        job = runner.jobs.get(job_id)
        if job and job.get("status") in {
            "succeeded",
            "completed",
            "degraded",
            "failed",
            "interrupted",
            "superseded",
        }:
            return job
        time.sleep(0.02)
    raise AssertionError("analysis job did not finish")


def test_submit_creates_one_parent_and_six_ordered_block_jobs(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    model = OrderedModel()
    coordinator = AnalysisCoordinator(
        runner.workspace_path,
        dependencies=runner.dependencies,
        job_service=runner.jobs,
        runner=runner,
    )

    state = runner._load_state()
    parent = coordinator.submit(
        model,
        input_hash=runner._input_hash(state),
        mode="incremental",
        delta_region_ids=(),
        snapshot_revision=int(state.get("revision", 0) or 0),
        snapshot_content_revision=int(state.get("content_revision", 0) or 0),
        analysis_config_hash="config-1",
    )

    completed = _wait(runner, str(parent["id"]))
    records = [
        item
        for item in runner.jobs.list()
        if item.get("kind") == "requirements.analysis.block"
        and item.get("payload", {}).get("parent_job_id") == parent["id"]
    ]
    expected = [
        "system_scope",
        "stakeholders",
        "concerns_needs",
        "requirements",
        "scenarios",
        "architecture",
    ]

    assert completed["kind"] == "requirements.analysis"
    assert completed["status"] == "succeeded"
    assert model.calls == expected
    assert [item["payload"]["block_id"] for item in records] == expected
    assert len(records) == 6
    assert all(item["payload"]["parent_job_id"] == parent["id"] for item in records)
    assert all(item["payload"]["input_hash"] == parent["payload"]["input_hash"] for item in records)
    assert completed["child_job_ids"] == [item["id"] for item in records]


def test_failed_child_does_not_block_later_children_and_retry_preserves_successes(
    tmp_path: Path,
) -> None:
    runner = _runner(tmp_path)
    model = OrderedModel(failing="requirements")
    coordinator = AnalysisCoordinator(
        runner.workspace_path,
        dependencies=runner.dependencies,
        job_service=runner.jobs,
        runner=runner,
    )
    state = runner._load_state()
    parent = coordinator.submit(
        model,
        input_hash=runner._input_hash(state),
        mode="incremental",
        delta_region_ids=(),
        snapshot_revision=int(state.get("revision", 0) or 0),
        snapshot_content_revision=int(state.get("content_revision", 0) or 0),
        analysis_config_hash="config-1",
    )

    completed = _wait(runner, str(parent["id"]))
    assert completed["status"] == "degraded"
    assert model.calls == [
        "system_scope",
        "stakeholders",
        "concerns_needs",
        "requirements",
        "scenarios",
        "architecture",
    ]
    children = [
        item
        for item in runner.jobs.list()
        if item.get("kind") == "requirements.analysis.block"
        and item.get("payload", {}).get("parent_job_id") == parent["id"]
    ]
    assert {item["payload"]["block_id"]: item["status"] for item in children}["requirements"] == "failed"
    assert {item["payload"]["block_id"]: item["status"] for item in children}["architecture"] == "succeeded"

    model.failing = None
    retry = coordinator.retry_failed(str(parent["id"]), model)
    retried = _wait(runner, str(retry["id"]))
    assert retried["status"] == "succeeded"
    assert model.calls[-1] == "requirements"
    assert model.calls.count("architecture") == 1
    retry_children = [
        item
        for item in runner.jobs.list()
        if item.get("kind") == "requirements.analysis.block"
        and item.get("payload", {}).get("parent_job_id") == retry["id"]
    ]
    assert [item["payload"]["block_id"] for item in retry_children] == ["requirements"]
