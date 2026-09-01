from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from rflp_lite.adapters.sqlite_job_repository import SQLiteJobRepository


def test_submit_persists_query_fields_and_block_state(tmp_path: Path) -> None:
    repository = SQLiteJobRepository(tmp_path / "model.db")

    queued = repository.submit(
        "enrichment",
        {
            "workspace": "demo",
            "idempotency_key": "request-1",
            "snapshot_revision": 4,
            "snapshot_content_revision": 2,
            "input_hash": "input-hash",
            "blocks": {"requirements": "queued", "scenarios": "queued"},
        },
    )

    assert queued["status"] == "queued"
    assert queued["workspace"] == "demo"
    assert queued["snapshot_revision"] == 4
    assert queued["snapshot_content_revision"] == 2
    assert queued["block_states"] == {"requirements": "queued", "scenarios": "queued"}

    running = repository.update(
        str(queued["id"]),
        {
            "status": "running",
            "blocks": {
                "requirements": {
                    "status": "succeeded",
                    "attempt": 1,
                    "result": {"count": 2},
                },
                "scenarios": "running",
            },
        },
    )
    assert running is not None
    assert running["block_states"] == {"requirements": "succeeded", "scenarios": "running"}

    completed = repository.update(
        str(queued["id"]),
        {"status": "succeeded", "result": {"status": "completed"}},
    )
    assert completed is not None
    assert completed["status"] == "succeeded"
    assert completed["result"] == {"status": "completed"}
    assert completed["blocks"]["requirements"] == "succeeded"
    repository.close()


def test_active_idempotency_reuses_only_active_jobs(tmp_path: Path) -> None:
    repository = SQLiteJobRepository(tmp_path / "model.db")
    first = repository.submit("demo", {"idempotency_key": "same"})
    active_duplicate = repository.submit("demo", {"idempotency_key": "same"})

    assert active_duplicate["id"] == first["id"]

    repository.update(str(first["id"]), {"status": "succeeded"})
    terminal_duplicate = repository.submit("demo", {"idempotency_key": "same"})
    assert terminal_duplicate["id"] != first["id"]
    repository.close()


def test_claim_has_one_winner_for_a_queued_job(tmp_path: Path) -> None:
    repository = SQLiteJobRepository(tmp_path / "model.db")
    queued = repository.submit("demo", {})

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(
            pool.map(lambda _item: repository.claim(str(queued["id"])), (1, 2))
        )

    assert sum(result is not None for result in results) == 1
    repository.close()


def test_update_round_trips_runtime_metadata_without_dropping_fields(tmp_path: Path) -> None:
    repository = SQLiteJobRepository(tmp_path / "model.db")
    queued = repository.submit("demo", {"idempotency_key": "metadata"})

    running = repository.claim(str(queued["id"]))
    assert running is not None
    updated = repository.update(
        str(queued["id"]),
        {
            "active_block": "requirements",
            "batch_index": 2,
            "retryable": True,
            "source_total": 8,
            "blocks": {"requirements": "running"},
        },
        expected_lease_id=str(running["lease_id"]),
    )

    assert updated is not None
    assert updated["active_block"] == "requirements"
    assert updated["batch_index"] == 2
    assert updated["retryable"] is True
    assert updated["source_total"] == 8
    assert updated["metadata"]["active_block"] == "requirements"

    repository.update(
        str(queued["id"]),
        {"status": "succeeded", "result": {"ok": True}},
        expected_lease_id=str(running["lease_id"]),
    )
    persisted = repository.get(str(queued["id"]))
    assert persisted is not None
    assert persisted["retryable"] is True
    assert persisted["active_block"] == "requirements"
    repository.close()


def test_stale_lease_cannot_update_after_recovery_and_retry(tmp_path: Path) -> None:
    repository = SQLiteJobRepository(tmp_path / "model.db")
    queued = repository.submit("demo", {})
    old = repository.claim(str(queued["id"]))
    assert old is not None

    repository.recover_startup(float(old["lease_expires_at"]) + 1)
    fresh = repository.retry_claim(str(queued["id"]))
    assert fresh is not None
    assert fresh["lease_id"] != old["lease_id"]

    stale = repository.update(
        str(queued["id"]),
        {"status": "succeeded", "result": {"stale": True}},
        expected_lease_id=str(old["lease_id"]),
    )
    current = repository.update(
        str(queued["id"]),
        {"status": "succeeded", "result": {"stale": False}},
        expected_lease_id=str(fresh["lease_id"]),
    )

    assert stale is None
    assert current is not None
    assert current["result"] == {"stale": False}
    repository.close()


def test_legacy_import_normalizes_completed_and_archives_after_commit(tmp_path: Path) -> None:
    database = tmp_path / "model.db"
    source = tmp_path / "jobs.json"
    archived = tmp_path / "jobs.legacy.json"
    source.write_text(
        json.dumps(
            [
                {
                    "id": "legacy-1",
                    "kind": "enrichment",
                    "status": "completed",
                    "attempt": 2,
                    "payload": {"workspace": "legacy", "input_hash": "hash"},
                    "block_states": {"requirements": "succeeded"},
                    "result": {"status": "completed"},
                }
            ]
        ),
        encoding="utf-8",
    )
    repository = SQLiteJobRepository(database)

    assert repository.import_legacy_file(source, archived) == 1
    assert not source.exists()
    assert archived.exists()
    imported = repository.get("legacy-1")
    assert imported is not None
    assert imported["status"] == "succeeded"
    assert imported["block_states"] == {"requirements": "succeeded"}
    assert repository.import_legacy_file(source, archived) == 0
    repository.close()


def test_failed_legacy_import_rolls_back_and_keeps_source(tmp_path: Path) -> None:
    source = tmp_path / "jobs.json"
    archived = tmp_path / "jobs.legacy.json"
    source.write_text(
        json.dumps(
            [
                {"id": "valid", "status": "queued", "payload": {}},
                {"id": "invalid", "status": "not-a-job-status", "payload": {}},
            ]
        ),
        encoding="utf-8",
    )
    repository = SQLiteJobRepository(tmp_path / "model.db")

    with pytest.raises(ValueError, match="unknown legacy job status"):
        repository.import_legacy_file(source, archived)

    assert source.exists()
    assert not archived.exists()
    assert repository.list() == ()
    repository.close()


def test_malformed_legacy_json_is_not_renamed(tmp_path: Path) -> None:
    source = tmp_path / "jobs.json"
    archived = tmp_path / "jobs.legacy.json"
    source.write_text("not-json", encoding="utf-8")
    repository = SQLiteJobRepository(tmp_path / "model.db")

    with pytest.raises(json.JSONDecodeError):
        repository.import_legacy_file(source, archived)

    assert source.exists()
    assert not archived.exists()
    repository.close()
