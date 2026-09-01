from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tests.job_helpers import make_job_service


def test_expired_running_job_recovers_to_interrupted(tmp_path: Path) -> None:
    service = make_job_service(tmp_path, lease_seconds=10)
    release = threading.Event()
    record = service.submit_async(
        "demo",
        {"blocks": {"a": "queued"}},
        lambda: {"status": "interrupted"} if release.wait(2) else {"status": "interrupted"},
    )
    for _ in range(20):
        current = service.get(str(record["id"]))
        if current and current.get("status") == "running":
            break
        time.sleep(0.01)
    service.update(
        str(record["id"]),
        {"status": "running", "lease_id": "old", "lease_expires_at": 1.0, "block_states": {"a": "running"}},
    )
    recovered = make_job_service(tmp_path, lease_seconds=10).get(str(record["id"]))
    assert recovered is not None
    assert recovered["status"] == "interrupted"
    assert recovered["block_states"]["a"] == "interrupted"
    assert recovered["last_error"]["type"] == "StartupRecovery"
    release.set()


def test_heartbeat_extends_valid_lease(tmp_path: Path) -> None:
    service = make_job_service(tmp_path, lease_seconds=10)
    release = threading.Event()
    record = service.submit_async(
        "demo", {}, lambda: (release.wait(2) or {"status": "succeeded"})
    )
    for _ in range(20):
        current = service.get(str(record["id"]))
        if current and current.get("status") == "running":
            break
        time.sleep(0.01)
    current = service.get(str(record["id"]))
    assert current is not None
    heartbeat = service.heartbeat(str(record["id"]), str(current["lease_id"]))
    assert heartbeat is not None
    assert heartbeat["lease_expires_at"] > heartbeat["heartbeat_at"]
    release.set()


def test_failed_job_retry_increments_attempt_and_succeeds(tmp_path: Path) -> None:
    service = make_job_service(tmp_path)
    with pytest.raises(RuntimeError, match="boom"):
        service.submit("demo", {}, lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    record = service.list()[0]
    assert record["status"] == "failed"
    retried = service.retry(str(record["id"]), lambda: {"status": "succeeded", "value": 1})
    assert retried["status"] == "succeeded"
    assert retried["attempt"] == 2
    assert retried["last_error"] is None


def test_terminal_idempotency_key_can_run_again_for_new_analysis(tmp_path: Path) -> None:
    service = make_job_service(tmp_path)
    first = service.submit("demo", {"idempotency_key": "same"}, lambda: {"status": "succeeded"})
    second = service.submit("demo", {"idempotency_key": "same"}, lambda: {"status": "succeeded"})
    assert second["id"] != first["id"]


def test_active_idempotency_key_reuses_one_async_job(tmp_path: Path) -> None:
    service = make_job_service(tmp_path, lease_seconds=10)
    release = threading.Event()
    first = service.submit_async(
        "demo",
        {"idempotency_key": "same-active", "blocks": {"a": "queued"}},
        lambda: {"status": "succeeded"} if release.wait(2) else {"status": "succeeded"},
    )
    second = service.submit_async(
        "demo",
        {"idempotency_key": "same-active", "blocks": {"a": "queued"}},
        lambda: pytest.fail("must not run twice"),
    )
    assert second["id"] == first["id"]
    assert len(service.list()) == 1
    release.set()


def test_concurrent_async_submit_executes_idempotent_runner_once(tmp_path: Path) -> None:
    service = make_job_service(tmp_path, lease_seconds=10)
    barrier = threading.Barrier(2)
    started = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def runner():
        nonlocal calls
        with calls_lock:
            calls += 1
        started.set()
        release.wait(2)
        return {"status": "succeeded"}

    def submit_once():
        barrier.wait()
        return service.submit_async(
            "demo", {"idempotency_key": "same-concurrent"}, runner
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = tuple(pool.map(lambda _item: submit_once(), (1, 2)))

    assert first["id"] == second["id"]
    assert started.wait(1)
    release.set()
    for _ in range(50):
        if service.get(str(first["id"]))["status"] == "succeeded":
            break
        time.sleep(0.01)
    assert calls == 1
    assert service.get(str(first["id"]))["status"] == "succeeded"


def test_concurrent_retry_claim_executes_runner_once(tmp_path: Path) -> None:
    service = make_job_service(tmp_path)
    with pytest.raises(RuntimeError, match="boom"):
        service.submit("demo", {}, lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    job_id = str(service.list()[0]["id"])
    barrier = threading.Barrier(2)
    started = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def runner():
        nonlocal calls
        with calls_lock:
            calls += 1
        started.set()
        release.wait(2)
        return {"status": "succeeded"}

    def retry_once():
        barrier.wait()
        try:
            return service.retry(job_id, runner)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = tuple(pool.map(lambda _item: retry_once(), (1, 2)))

    assert (first is None) != (second is None)
    assert started.wait(1)
    release.set()
    for _ in range(50):
        if service.get(job_id)["status"] == "succeeded":
            break
        time.sleep(0.01)
    assert calls == 1
    assert service.get(job_id)["attempt"] == 2


def test_retry_rejects_non_object_runner_result(tmp_path: Path) -> None:
    service = make_job_service(tmp_path)
    with pytest.raises(RuntimeError, match="boom"):
        service.submit("demo", {}, lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    job_id = str(service.list()[0]["id"])

    retried = service.retry(job_id, lambda: object())

    assert retried["status"] == "failed"
    assert retried["last_error"]["type"] == "TypeError"
