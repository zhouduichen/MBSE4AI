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


def test_requirement_ledger_keeps_a_deleted_tombstone(tmp_path):
    repo = SQLiteRepository(tmp_path / "model.db")
    with repo.transaction():
        sequence = repo.record_audit("requirements.analyzed", {"name": "requirements.txt"})
        repo.save_requirement_records(
            (
                {
                    "id": "claim-1",
                    "subject": "管理员",
                    "predicate": "必须",
                    "object": "恢复历史版本",
                    "status": "accepted",
                    "source_type": "need",
                },
            ),
            sequence,
            "requirements.analyzed",
        )
        deleted_sequence = repo.record_audit("requirements.deleted", {"id": "claim-1"})
        repo.mark_requirement_deleted(("claim-1",), deleted_sequence, "requirements.deleted")

    record = repo.requirement_records()[0]
    assert record["status"] == "deleted"
    assert record["first_seen_sequence"] == sequence
    assert record["last_seen_sequence"] == deleted_sequence
    assert record["history"][-1]["event"] == "requirements.deleted"
