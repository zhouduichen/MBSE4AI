import pytest

from rflp_lite.adapters.sqlite_repository import SQLiteRepository
from rflp_lite.domain.baseline import approve_baseline
from rflp_lite.domain.models import ModelElement


def approved_baseline():
    return approve_baseline((ModelElement("req-1", "R", "Restore a version"),), ())


def test_transaction_rolls_back_without_changing_baseline(tmp_path):
    repo = SQLiteRepository(tmp_path / "model.db")
    baseline = repo.save_baseline(approved_baseline())
    before = repo.latest_baseline().hash
    with pytest.raises(RuntimeError):
        with repo.transaction():
            repo.record_audit("adapter.started", {"name": "broken"})
            raise RuntimeError("boom")
    assert repo.latest_baseline().hash == before == baseline.hash
    assert repo.audit_events() == ()

