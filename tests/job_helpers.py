from __future__ import annotations

from pathlib import Path

from rflp_lite.adapters.sqlite_job_repository import SQLiteJobRepository
from rflp_lite.adapters.thread_background_executor import ThreadBackgroundExecutor
from rflp_lite.application.jobs import JobService
from rflp_lite.bootstrap.legacy_job_migration import migrate_legacy_jobs


def make_job_service(path: Path, *, lease_seconds: float = 30.0) -> JobService:
    repository = SQLiteJobRepository(
        path / ".rflp" / "model.db", lease_seconds=lease_seconds
    )
    migrate_legacy_jobs(path, repository)
    return JobService(
        path,
        lease_seconds=lease_seconds,
        repository=repository,
        executor=ThreadBackgroundExecutor(),
    )
