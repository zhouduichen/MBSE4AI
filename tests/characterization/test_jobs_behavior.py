from pathlib import Path

from tests.job_helpers import make_job_service


def test_job_characterization_keeps_success_and_result(tmp_path: Path) -> None:
    service = make_job_service(tmp_path)

    result = service.submit("demo", {"value": 1}, lambda: {"answer": 42})

    assert result["status"] == "succeeded"
    assert result["result"] == {"answer": 42}
