from __future__ import annotations

import pytest

from rflp_lite.application.jobs import JobService


def test_job_service_persists_success_and_can_reload(tmp_path):
    service = JobService(tmp_path)

    job = service.submit("demo", {"value": 1}, lambda: {"answer": 42})

    assert job["status"] == "succeeded"
    assert job["result"] == {"answer": 42}
    assert service.get(job["id"]) == job


def test_job_service_retains_failure(tmp_path):
    service = JobService(tmp_path)

    with pytest.raises(ValueError, match="broken"):
        service.submit("demo", {}, lambda: (_ for _ in ()).throw(ValueError("broken")))

    stored = service.list()[0]
    assert stored["status"] == "failed"
    assert stored["error"]["message"] == "broken"


def test_job_service_unknown_job_is_none(tmp_path):
    assert JobService(tmp_path).get("job-missing") is None
