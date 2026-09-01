from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from rflp_lite.application.job_state import ACTIVE_JOB_STATUSES, TERMINAL_JOB_STATUSES
from rflp_lite.domain.canonical import canonical_json
from rflp_lite.ports.jobs import BackgroundExecutorPort, JobRepositoryPort


JobRunner = Callable[[], dict[str, object]]
JOB_STATES = ACTIVE_JOB_STATUSES | TERMINAL_JOB_STATUSES
DEFAULT_LEASE_SECONDS = 30.0
_JOB_LOCKS: dict[str, threading.RLock] = {}
_JOB_LOCKS_GUARD = threading.Lock()


class JobService:
    """Small durable job ledger for local synchronous operations."""

    def __init__(
        self,
        workspace_path: Path,
        *,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
        repository: JobRepositoryPort,
        executor: BackgroundExecutorPort,
    ):
        self.directory = workspace_path / ".rflp"
        self.database_path = self.directory / "model.db"
        self.lease_seconds = max(1.0, float(lease_seconds))
        key = str(self.database_path.resolve())
        with _JOB_LOCKS_GUARD:
            self._lock = _JOB_LOCKS.setdefault(key, threading.RLock())
        self._execution_context = threading.local()
        self._repository = repository
        self._executor = executor
        self.recover_startup()

    def _load(self) -> list[dict[str, object]]:
        return list(self._repository.list())

    @staticmethod
    def _active_match(
        jobs: list[dict[str, object]], idempotency_key: str
    ) -> dict[str, object] | None:
        if not idempotency_key:
            return None
        return next(
            (
                item
                for item in jobs
                if item.get("idempotency_key") == idempotency_key
                and item.get("status") in {"queued", "running"}
            ),
            None,
        )

    @staticmethod
    def _new_record(
        kind: str, payload: dict[str, object], job_id: str
    ) -> dict[str, object]:
        idempotency_key = str(payload.get("idempotency_key", "")).strip()
        blocks = (
            dict(payload.get("blocks", {}))
            if isinstance(payload.get("blocks"), dict)
            else {}
        )
        return {
            "id": job_id,
            "kind": kind,
            "payload": json.loads(canonical_json(payload)),
            "status": "queued",
            "attempt": 0,
            "lease_id": "",
            "lease_expires_at": 0.0,
            "heartbeat_at": 0.0,
            "last_error": None,
            "blocks": blocks,
            "block_states": dict(blocks),
            "idempotency_key": idempotency_key,
        }

    def submit(self, kind: str, payload: dict[str, object], runner: JobRunner) -> dict[str, object]:
        with self._lock:
            record = self._repository.submit(kind, payload)
            if record.get("status") in ACTIVE_JOB_STATUSES and record.get("status") != "queued":
                return json.loads(canonical_json(record))
            job_id = str(record["id"])
            claimed = self._repository.claim(job_id)
            if claimed is None:
                return json.loads(
                    canonical_json(self.get(job_id) or record)
                )
        lease_id = str(claimed.get("lease_id", ""))
        with self._lease_context(job_id, lease_id):
            try:
                result = runner()
                if not isinstance(result, dict):
                    raise TypeError("job runner must return an object")
            except BaseException as exc:
                self.update(
                    job_id,
                    {
                        "status": "failed",
                        "error": {"type": type(exc).__name__, "message": str(exc)},
                        "last_error": {"type": type(exc).__name__, "message": str(exc)},
                        "retryable": True,
                    },
                )
                raise
            final_status = str(result.get("status", "succeeded"))
            if final_status not in {"succeeded", "degraded", "failed", "interrupted", "superseded"}:
                final_status = "succeeded"
            return self.update(
                job_id, {"status": final_status, "result": result}
            ) or self.get(job_id) or record

    def submit_async(
        self, kind: str, payload: dict[str, object], runner: JobRunner
    ) -> dict[str, object]:
        """Persist a job and run it on a local daemon worker."""

        with self._lock:
            record = self._repository.submit(kind, payload)
            job_id = str(record["id"])
            if record.get("status") != "queued":
                return json.loads(canonical_json(record))
            claimed = self._repository.claim(job_id)
            if claimed is None:
                return json.loads(
                    canonical_json(self.get(job_id) or record)
                )
        lease_id = str(claimed.get("lease_id", ""))

        def worker() -> None:
            with self._lease_context(job_id, lease_id):
                try:
                    result = runner()
                    if not isinstance(result, dict):
                        raise TypeError("job runner must return an object")
                except BaseException as exc:
                    self.update(
                        job_id,
                        {
                            "status": "failed",
                            "error": {"type": type(exc).__name__, "message": str(exc)},
                            "last_error": {"type": type(exc).__name__, "message": str(exc)},
                            "retryable": True,
                        },
                    )
                    return
                result_status = str(result.get("status", ""))
                final_status = result_status if result_status in TERMINAL_JOB_STATUSES else "succeeded"
                self.update(job_id, {"status": final_status, "result": result})

        self._executor.submit(job_id, worker)
        return json.loads(canonical_json(self.get(job_id) or record))

    def update(self, job_id: str, patch: dict[str, object]) -> dict[str, object] | None:
        """Atomically merge a partial job update into the durable ledger."""

        context_job_id = getattr(self._execution_context, "job_id", None)
        expected_lease_id = (
            str(getattr(self._execution_context, "lease_id", ""))
            if context_job_id == job_id
            else None
        )
        return self._repository.update(
            job_id,
            patch,
            expected_lease_id=expected_lease_id or None,
        )

    def get(self, job_id: str) -> dict[str, object] | None:
        return self._repository.get(job_id)

    def list(self) -> tuple[dict[str, Any], ...]:
        return self._repository.list()

    def _start_patch(self) -> dict[str, object]:
        now = time.time()
        return {
            "status": "running",
            "attempt": 1,
            "lease_id": uuid.uuid4().hex,
            "lease_expires_at": now + self.lease_seconds,
            "heartbeat_at": now,
            "last_error": None,
        }

    def _start_record(self, record: dict[str, object]) -> None:
        patch = self._start_patch()
        record.update(patch)

    def recover_startup(self, now: float | None = None) -> tuple[dict[str, object], ...]:
        current_time = time.time() if now is None else float(now)
        return self._repository.recover_startup(current_time)

    def heartbeat(
        self, job_id: str, lease_id: str, now: float | None = None
    ) -> dict[str, object] | None:
        current_time = time.time() if now is None else float(now)
        return self._repository.heartbeat(job_id, lease_id, current_time)

    def retry(self, job_id: str, runner: JobRunner) -> dict[str, object]:
        record = self.get(job_id)
        if record is None:
            raise KeyError(job_id)
        if record.get("status") not in {"failed", "degraded", "interrupted"}:
            raise ValueError("only failed, degraded, or interrupted jobs can be retried")
        claimed = self._repository.retry_claim(job_id)
        if claimed is None:
            raise ValueError("job is no longer retryable")
        lease_id = str(claimed.get("lease_id", ""))
        with self._lease_context(job_id, lease_id):
            try:
                result = runner()
                if not isinstance(result, dict):
                    raise TypeError("job runner must return an object")
                final_status = str(result.get("status", "succeeded"))
                if final_status not in TERMINAL_JOB_STATUSES:
                    final_status = "succeeded"
                return self.update(
                    job_id,
                    {"status": final_status, "result": result, "last_error": None},
                ) or self.get(job_id) or record
            except BaseException as exc:
                return self.update(
                    job_id,
                    {
                        "status": "failed",
                        "last_error": {"type": type(exc).__name__, "message": str(exc)},
                        "error": {"type": type(exc).__name__, "message": str(exc)},
                        "retryable": True,
                    },
                ) or self.get(job_id) or record

    @contextmanager
    def _lease_context(self, job_id: str, lease_id: str):
        previous = (
            getattr(self._execution_context, "job_id", None),
            getattr(self._execution_context, "lease_id", None),
        )
        self._execution_context.job_id = job_id
        self._execution_context.lease_id = lease_id
        try:
            yield
        finally:
            if previous[0] is None:
                for name in ("job_id", "lease_id"):
                    try:
                        delattr(self._execution_context, name)
                    except AttributeError:
                        pass
            else:
                self._execution_context.job_id = previous[0]
                self._execution_context.lease_id = previous[1]
