"""Startup-only migration for the pre-SQLite job ledger."""

from __future__ import annotations

from pathlib import Path

from rflp_lite.ports.jobs import LegacyJobMigrationPort


def migrate_legacy_jobs(
    workspace_path: Path, repository: LegacyJobMigrationPort
) -> int:
    directory = workspace_path / ".rflp"
    return repository.import_legacy_file(
        directory / "jobs.json",
        directory / "jobs.legacy.json",
    )
