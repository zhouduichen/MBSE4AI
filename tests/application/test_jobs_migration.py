from __future__ import annotations

import json
from pathlib import Path

from rflp_lite.application.jobs import JobService


def test_job_service_imports_legacy_jobs_once_and_reloads_from_sqlite(tmp_path: Path) -> None:
    legacy_path = tmp_path / ".rflp" / "jobs.json"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_text(
        json.dumps(
            [
                {
                    "id": "legacy-job",
                    "kind": "demo",
                    "status": "completed",
                    "payload": {"workspace": "demo"},
                    "result": {"status": "completed", "answer": 42},
                }
            ]
        ),
        encoding="utf-8",
    )

    first = JobService(tmp_path)
    assert len(first.list()) == 1
    assert first.get("legacy-job")["status"] == "succeeded"
    assert not legacy_path.exists()
    assert (tmp_path / ".rflp" / "jobs.legacy.json").exists()

    second = JobService(tmp_path)
    assert [item["id"] for item in second.list()] == ["legacy-job"]
