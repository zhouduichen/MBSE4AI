from __future__ import annotations

from pathlib import Path

import pytest

from rflp_lite.adapters.sqlite_repository import SQLiteRepository
from rflp_lite.application.workbench import (
    MutationKind,
    MutationResult,
    WorkbenchCommitCoordinator,
)
from rflp_lite.domain.errors import ConcurrentModificationError


def test_coordinator_commits_mutation_and_audit_atomically(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "model.db")
    coordinator = WorkbenchCommitCoordinator(repository, "demo")

    result = coordinator.commit(
        lambda state: MutationResult(
            state={**state, "content_revision": 1, "label": "human"},
            changed_ids=("req-1",),
            mutation_kind=MutationKind.HUMAN_CONTENT,
        ),
        expected_revision=0,
        expected_content_revision=0,
        event="requirements.edited",
    )

    assert result.state["revision"] == 1
    assert result.state["content_revision"] == 1
    assert repository.audit_events()[-1]["kind"] == "requirements.edited"
    repository.close()


def test_coordinator_rejects_stale_snapshot_without_side_effects(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "model.db")
    coordinator = WorkbenchCommitCoordinator(repository, "demo")
    coordinator.commit(
        lambda state: MutationResult(state={**state, "content_revision": 1}),
        expected_revision=0,
        expected_content_revision=0,
        event="requirements.created",
    )

    with pytest.raises(ConcurrentModificationError):
        coordinator.commit(
            lambda state: MutationResult(state={**state, "content_revision": 2}),
            expected_revision=0,
            expected_content_revision=0,
            event="requirements.stale",
        )

    assert repository.load_workbench()["content_revision"] == 1
    assert all(item["kind"] != "requirements.stale" for item in repository.audit_events())
    repository.close()
