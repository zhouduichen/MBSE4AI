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


def test_workbench_summary_tracks_claims_and_model_state(tmp_path):
    repo = SQLiteRepository(tmp_path / "model.db")

    repo.save_workbench({"claims": []})
    assert repo.load_workbench_summary() == {
        "revision": 1,
        "content_revision": 0,
        "requirement_count": 0,
        "accepted_count": 0,
        "model_state": "未生成",
        "updated_at": repo.load_workbench_summary()["updated_at"],
    }

    repo.save_workbench(
        {
            "claims": [
                {"id": "claim-1", "status": "accepted"},
                {"id": "claim-2", "status": "candidate"},
            ],
            "draft": {"status": "draft"},
        }
    )
    draft_summary = repo.load_workbench_summary()
    assert draft_summary is not None
    assert draft_summary["revision"] == 2
    assert draft_summary["requirement_count"] == 2
    assert draft_summary["accepted_count"] == 1
    assert draft_summary["model_state"] == "草稿"

    repo.save_workbench(
        {
            "claims": [{"id": "claim-1", "status": "accepted"}],
            "rflp": {"elements": [], "relations": []},
        }
    )
    formal_summary = repo.load_workbench_summary()
    assert formal_summary is not None
    assert formal_summary["requirement_count"] == 1
    assert formal_summary["accepted_count"] == 1
    assert formal_summary["model_state"] == "正式模型"
    repo.close()


def test_legacy_workbench_without_summary_is_not_loaded_for_overview(tmp_path):
    repo = SQLiteRepository(tmp_path / "model.db")
    repo._connection.execute(
        "INSERT INTO workbench(id, revision, content_revision, payload) VALUES (?, ?, ?, ?)",
        ("current", 7, 3, '{"claims": [{"id": "legacy"}]}'),
    )

    assert repo.load_workbench_summary() is None
    repo.close()
