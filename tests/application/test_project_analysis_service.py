from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import rflp_lite.application.dependencies as dependency_registry
from rflp_lite.application.use_cases.project_analysis import (
    ProjectAnalysisDependencies,
    ProjectAnalysisService,
)
from rflp_lite.application.workspaces import WorkspaceRef


class FakeRepository:
    def __init__(self):
        self.saved = []
        self.baselines = []
        self.evidence = []
        self.tasks = []
        self.events = []
        self.closed = False

    @contextmanager
    def transaction(self):
        yield

    def save_workbench(self, state):
        self.saved.append(state)

    def save_baseline(self, baseline):
        self.baselines.append(baseline)

    def save_evidence(self, evidence):
        self.evidence.append(tuple(evidence))

    def save_tasks(self, tasks):
        self.tasks.append(tuple(tasks))

    def record_audit(self, kind, payload):
        self.events.append((kind, dict(payload)))
        return len(self.events)

    def close(self):
        self.closed = True


def test_analyze_persists_project_analysis_with_explicit_dependencies(
    tmp_path: Path, monkeypatch
):
    workspace = WorkspaceRef(
        "demo", tmp_path / "demo", tmp_path / "demo" / "profile.json", True
    )
    workspace.path.mkdir(parents=True)
    state = {"project": {"source": str(tmp_path / "project")}}
    artifacts = SimpleNamespace(
        baseline=object(),
        evidence=("evidence-1",),
        tasks=("task-1",),
        delta=SimpleNamespace(
            items=(SimpleNamespace(kind="MISSING"), SimpleNamespace(kind="EXTRA"))
        ),
    )
    repository = FakeRepository()
    calls = []

    def analyze(current, source):
        calls.append((current, source))
        return state, artifacts

    service = ProjectAnalysisService(
        ProjectAnalysisDependencies(
            repository_factory=lambda _path: repository,
            load_state=lambda _workspace: state,
            analyze_state=analyze,
        )
    )
    monkeypatch.setattr(dependency_registry, "_DEFAULT_DEPENDENCIES", None)

    result = service.analyze(workspace, "project")

    assert result is state
    assert calls == [(state, "project")]
    assert repository.saved == [state]
    assert repository.baselines == [artifacts.baseline]
    assert repository.evidence == [("evidence-1",)]
    assert repository.tasks == [("task-1",)]
    assert repository.events == [
        (
            "project.analyzed",
            {"source": state["project"]["source"], "missing": 1, "extra": 1, "tasks": 1},
        )
    ]
    assert repository.closed is True
