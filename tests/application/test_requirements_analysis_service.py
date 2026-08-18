from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

import rflp_lite.application.dependencies as dependency_registry
from rflp_lite.application.requirements_workbench import empty_workbench
from rflp_lite.application.use_cases.requirements_analysis import (
    RequirementsAnalysisDependencies,
    RequirementsAnalysisService,
)
from rflp_lite.application.workspaces import WorkspaceRef


class FakeRepository:
    def __init__(self, state=None):
        self.state = deepcopy(state)
        self.events: list[tuple[str, dict[str, object]]] = []
        self.saved_events: list[str] = []
        self.requirement_records = []
        self.trace_records = []

    @contextmanager
    def transaction(self):
        yield

    def save_workbench(self, value, event="workbench.saved"):
        self.state = deepcopy(value)
        self.saved_events.append(event)
        return value

    def record_audit(self, kind, payload):
        self.events.append((kind, dict(payload)))
        return len(self.events)

    def save_requirement_records(self, values, sequence, event):
        self.requirement_records.append((tuple(values), sequence, event))

    def save_trace_records(self, values):
        self.trace_records.append(tuple(values))

    def close(self):
        return None


class FakeJobService:
    def __init__(self, previous=None):
        self.previous = previous

    def get(self, job_id):
        return self.previous if self.previous and self.previous["id"] == job_id else None


class FakeRunner:
    def __init__(self, result):
        self.result = result
        self.submissions = []
        self.retries = []

    def submit(self, model, *, input_hash=None):
        self.submissions.append((model, input_hash))
        return deepcopy(self.result)

    def retry(self, job_id, model):
        self.retries.append((job_id, model))
        return deepcopy(self.result)


def _state() -> dict[str, object]:
    state = empty_workbench()
    state["artifact"] = {
        "id": "artifact-seed",
        "kind": "txt",
        "path": "seed.txt",
        "sha256": "a" * 64,
    }
    state["spans"] = [
        {
            "id": "span-1",
            "artifact_id": "artifact-seed",
            "locator": "paragraph-1",
            "text": "系统应支持备份",
        }
    ]
    state["claims"] = [
        {
            "id": "claim-1",
            "span_id": "span-1",
            "subject": "系统",
            "predicate": "应支持",
            "object": "备份",
            "status": "accepted",
            "source_type": "constraint",
            "candidate_type": "constraint",
            "interpretation": "约束",
            "confidence": 1.0,
        }
    ]
    return state


def _service(tmp_path: Path, *, job_result, previous=None):
    state = _state()
    repository = FakeRepository(state if previous is not None else None)
    jobs = FakeJobService(previous)
    runner = FakeRunner(job_result)
    workspace = WorkspaceRef(
        "demo", tmp_path / "demo", tmp_path / "demo" / "profile.json", True
    )
    workspace.path.mkdir(parents=True)

    def load_state(_workspace):
        return deepcopy(repository.state)

    def analyze(filename, _content):
        result = deepcopy(state)
        result["artifact"] = {**result["artifact"], "path": filename}
        return result

    def merge(current, filename, _content):
        result = deepcopy(current)
        result["artifact"] = {**result["artifact"], "path": filename}
        return result

    service = RequirementsAnalysisService(
        RequirementsAnalysisDependencies(
            repository_factory=lambda _path: repository,
            job_service_factory=lambda _path: jobs,
            enrichment_runner_factory=lambda _path: runner,
            load_state=load_state,
            analyze_artifact=analyze,
            merge_artifact=merge,
        )
    )
    return service, workspace, repository, runner


def test_analyze_persists_baseline_then_queues_enrichment(tmp_path):
    service, workspace, repository, runner = _service(
        tmp_path,
        job_result={"id": "job-1", "status": "queued", "blocks": {"requirements": "queued"}},
    )

    result = service.analyze(
        workspace,
        "requirements.txt",
        "系统应支持备份".encode(),
        merge=False,
        model=None,
    )

    assert result["artifact"]["path"] == "requirements.txt"
    assert repository.saved_events == [
        "requirements.analyzed",
        "requirements.enrichment_queued",
    ]
    assert [kind for kind, _payload in repository.events] == [
        "requirements.analyzed",
        "requirements.enrichment_queued",
        "requirements.traceability_updated",
    ]
    assert runner.submissions[0][1] == result["project_scope"]["input_hash"]
    assert (workspace.path / "inputs" / f'{result["artifact"]["sha256"][:12]}-requirements.txt').is_file()


def test_merge_persists_finished_enrichment_status(tmp_path):
    service, workspace, repository, runner = _service(
        tmp_path,
        job_result={
            "id": "job-2",
            "status": "degraded",
            "blocks": {"requirements": "failed"},
            "result": {"status": "degraded"},
        },
        previous={"id": "old-job", "status": "completed"},
    )

    result = service.analyze(
        workspace,
        "merged.txt",
        "新增约束".encode(),
        merge=True,
    )

    assert result["artifact"]["path"] == "merged.txt"
    assert repository.saved_events == [
        "requirements.merged",
        "requirements.enrichment_finished",
    ]
    assert result["auto_analysis"]["status"] == "degraded"
    assert runner.submissions[0][1] == result["project_scope"]["input_hash"]


def test_retry_uses_only_explicit_dependencies(tmp_path, monkeypatch):
    service, workspace, repository, runner = _service(
        tmp_path,
        job_result={"id": "retry-job", "status": "queued", "blocks": {}},
        previous={"id": "old-job", "input_hash": "input", "blocks": {}},
    )

    monkeypatch.setattr(dependency_registry, "_DEFAULT_DEPENDENCIES", None)

    result = service.retry(workspace, "old-job", model=object())

    assert result["id"] == "retry-job"
    assert runner.retries[0][0] == "old-job"
    assert repository.saved_events == ["requirements.enrichment_retry_queued"]
