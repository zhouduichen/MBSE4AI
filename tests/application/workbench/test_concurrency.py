from __future__ import annotations

from pathlib import Path

import pytest

from rflp_lite.adapters.sqlite_repository import SQLiteRepository
from rflp_lite.application.workbench import MutationResult, WorkbenchCommitCoordinator
from rflp_lite.domain.errors import ConcurrentModificationError


def test_stale_human_write_is_rejected_after_another_commit(tmp_path: Path) -> None:
    path = tmp_path / "model.db"
    first = SQLiteRepository(path)
    second = SQLiteRepository(path)
    first.save_workbench({"content_revision": 0, "label": "initial"}, expected_revision=0)

    coordinator = WorkbenchCommitCoordinator(first, "demo")
    coordinator.commit(
        lambda state: MutationResult(state={**state, "content_revision": 1, "label": "new"}),
        expected_revision=1,
        expected_content_revision=0,
        event="requirements.edited",
    )
    stale = WorkbenchCommitCoordinator(second, "demo")

    with pytest.raises(ConcurrentModificationError):
        stale.commit(
            lambda state: MutationResult(
                state={**state, "content_revision": 1, "label": "stale"}
            ),
            expected_revision=1,
            expected_content_revision=0,
            event="requirements.stale",
        )
    first.close()
    second.close()
