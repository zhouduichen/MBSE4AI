from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rflp_lite.domain.canonical import canonical_json


JobRunner = Callable[[], dict[str, object]]
_JOB_LOCKS: dict[str, threading.RLock] = {}
_JOB_LOCKS_GUARD = threading.Lock()


class JobService:
    """Small durable job ledger for local synchronous operations."""

    def __init__(self, workspace_path: Path):
        self.directory = workspace_path / ".rflp"
        self.path = self.directory / "jobs.json"
        key = str(self.path.resolve())
        with _JOB_LOCKS_GUARD:
            self._lock = _JOB_LOCKS.setdefault(key, threading.RLock())

    def _load(self) -> list[dict[str, object]]:
        with self._lock:
            if not self.path.is_file():
                return []
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, list):
                raise ValueError("jobs.json must contain a list")
            return [item for item in value if isinstance(item, dict)]

    def _save(self, jobs: list[dict[str, object]]) -> None:
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(prefix="jobs-", suffix=".json", dir=self.directory)
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as stream:
                    stream.write(canonical_json(jobs))
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            except BaseException:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
                raise

    def submit(self, kind: str, payload: dict[str, object], runner: JobRunner) -> dict[str, object]:
        job_id = f"job-{uuid.uuid4().hex[:12]}"
        record: dict[str, object] = {
            "id": job_id,
            "kind": kind,
            "payload": json.loads(canonical_json(payload)),
            "status": "queued",
        }
        with self._lock:
            jobs = self._load()
            jobs.append(record)
            self._save(jobs)

            record["status"] = "running"
            self._save(jobs)
        try:
            result = runner()
            if not isinstance(result, dict):
                raise TypeError("job runner must return an object")
        except BaseException as exc:
            record.update(
                {
                    "status": "failed",
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }
            )
            with self._lock:
                self._save(jobs)
            raise
        record.update({"status": "succeeded", "result": result})
        with self._lock:
            self._save(jobs)
        return json.loads(canonical_json(record))

    def submit_async(
        self, kind: str, payload: dict[str, object], runner: JobRunner
    ) -> dict[str, object]:
        """Persist a job and run it on a local daemon worker."""

        job_id = f"job-{uuid.uuid4().hex[:12]}"
        record: dict[str, object] = {
            "id": job_id,
            "kind": kind,
            "payload": json.loads(canonical_json(payload)),
            "status": "queued",
        }
        with self._lock:
            jobs = self._load()
            jobs.append(record)
            self._save(jobs)

        def worker() -> None:
            current = self.get(job_id)
            if current is None:
                return
            current["status"] = "running"
            self.update(job_id, current)
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
                    },
                )
                return
            result_status = str(result.get("status", ""))
            final_status = result_status if result_status in {"succeeded", "completed", "degraded"} else "succeeded"
            self.update(job_id, {"status": final_status, "result": result})

        thread = threading.Thread(target=worker, name=f"rflp-job-{job_id}", daemon=True)
        thread.start()
        return json.loads(canonical_json(self.get(job_id) or record))

    def update(self, job_id: str, patch: dict[str, object]) -> dict[str, object] | None:
        """Atomically merge a partial job update into the durable ledger."""

        with self._lock:
            jobs = self._load()
            record = next((item for item in jobs if item.get("id") == job_id), None)
            if record is None:
                return None
            record.update(json.loads(canonical_json(patch)))
            self._save(jobs)
            return json.loads(canonical_json(record))

    def get(self, job_id: str) -> dict[str, object] | None:
        return next((item for item in self._load() if item.get("id") == job_id), None)

    def list(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._load())
