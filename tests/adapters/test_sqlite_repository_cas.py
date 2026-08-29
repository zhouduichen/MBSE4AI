from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from rflp_lite.adapters.sqlite_repository import SQLiteRepository
from rflp_lite.domain.errors import ConcurrentModificationError


def _state(label: str) -> dict[str, object]:
    return {"content_revision": 0, "label": label}


def test_save_workbench_enforces_strict_compare_and_swap(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "model.db")
    first = repository.save_workbench(_state("first"), expected_revision=0)

    assert first["revision"] == 1
    with pytest.raises(ConcurrentModificationError):
        repository.save_workbench(_state("stale"), expected_revision=0)
    assert repository.load_workbench()["label"] == "first"
    repository.close()


def test_legacy_save_call_remains_compatible(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "model.db")
    saved = repository.save_workbench(_state("legacy"))

    assert saved["revision"] == 1
    assert repository.load_workbench()["label"] == "legacy"
    repository.close()


def test_two_repositories_protect_first_insert(tmp_path: Path) -> None:
    path = tmp_path / "model.db"
    first = SQLiteRepository(path)
    first.close()

    def attempt(label: str) -> str:
        repository = SQLiteRepository(path)
        try:
            repository.save_workbench(_state(label), expected_revision=0)
            return "saved"
        except ConcurrentModificationError:
            return "conflict"
        finally:
            repository.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(attempt, ("a", "b")))

    assert sorted(results) == ["conflict", "saved"]


def test_audit_and_workbench_rollback_together(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "model.db")
    with pytest.raises(RuntimeError, match="rollback"):
        with repository.transaction():
            repository.save_workbench(_state("rolled-back"), expected_revision=0)
            repository.record_audit("workbench.test", {"status": "pending"})
            raise RuntimeError("rollback")

    assert repository.load_workbench() is None
    assert repository.audit_events() == ()
    repository.close()
