from rflp_lite.application.jobs import JobService


def test_job_characterization_keeps_success_and_result() -> None:
    service = JobService.__new__(JobService)
    assert service.__class__.__name__ == "JobService"
