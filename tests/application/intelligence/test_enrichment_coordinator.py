from __future__ import annotations

from dataclasses import dataclass, field

from rflp_lite.application.intelligence.enrichment_coordinator import (
    BatchPlanner,
    BlockCommitter,
    BlockExecutor,
    EnrichmentCoordinator,
    EnrichmentSnapshot,
    Finalizer,
    ProgressReporter,
    SnapshotGuard,
)


@dataclass
class _Executor(BlockExecutor):
    def execute(self, block_id: str) -> object:
        if block_id == "broken":
            raise RuntimeError("provider failed")
        return {"id": block_id}


@dataclass
class _Committer(BlockCommitter):
    committed: list[str] = field(default_factory=list)

    def commit(self, block_id: str, result: object) -> object:
        self.committed.append(block_id)
        return result


class _Progress(ProgressReporter):
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def report(self, block_id: str, status: str, diagnostics=()) -> None:
        self.events.append((block_id, status))


def test_coordinator_preserves_successful_blocks_when_one_block_fails() -> None:
    committer = _Committer()
    progress = _Progress()
    coordinator = EnrichmentCoordinator(
        SnapshotGuard(), BatchPlanner(), _Executor(), committer, progress, Finalizer()
    )
    result = coordinator.run(
        {"revision": 2, "content_revision": 3, "project_scope": {"input_hash": "h"}},
        EnrichmentSnapshot(2, 3, "h"),
        ("requirements", "broken", "scenarios"),
    )

    assert result["status"] == "degraded"
    assert committer.committed == ["requirements", "scenarios"]
    assert result["results"]["requirements"] == {"id": "requirements"}


def test_coordinator_skips_successful_blocks_on_resume_and_rejects_stale_snapshot() -> None:
    committer = _Committer()
    coordinator = EnrichmentCoordinator(
        SnapshotGuard(), BatchPlanner(), _Executor(), committer, ProgressReporter(), Finalizer()
    )
    state = {"revision": 2, "content_revision": 3, "project_scope": {"input_hash": "h"}}
    resumed = coordinator.run(state, EnrichmentSnapshot(2, 3, "h"), ("requirements", "scenarios"), completed=("requirements",))
    stale = coordinator.run(state, EnrichmentSnapshot(2, 4, "h"), ("requirements",))

    assert resumed["status"] == "succeeded"
    assert committer.committed == ["scenarios"]
    assert stale["status"] == "superseded"
