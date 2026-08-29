from pathlib import Path

from rflp_lite.application.jobs import JobService


def test_job_characterization_keeps_success_and_result(tmp_path: Path) -> None:
    service = JobService(tmp_path)

    result = service.submit("demo", {"value": 1}, lambda: {"answer": 42})

    assert result["status"] == "succeeded"
    assert result["result"] == {"answer": 42}
