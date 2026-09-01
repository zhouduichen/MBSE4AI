from __future__ import annotations

import pytest

from tests.job_helpers import make_job_service


def test_job_service_persists_success_and_can_reload(tmp_path):
    service = make_job_service(tmp_path)

    job = service.submit("demo", {"value": 1}, lambda: {"answer": 42})

    assert job["status"] == "succeeded"
    assert job["result"] == {"answer": 42}
    assert service.get(job["id"]) == job


def test_job_service_retains_failure(tmp_path):
    service = make_job_service(tmp_path)

    with pytest.raises(ValueError, match="broken"):
        service.submit("demo", {}, lambda: (_ for _ in ()).throw(ValueError("broken")))

    stored = service.list()[0]
    assert stored["status"] == "failed"
    assert stored["error"]["message"] == "broken"


def test_job_service_unknown_job_is_none(tmp_path):
    assert make_job_service(tmp_path).get("job-missing") is None
