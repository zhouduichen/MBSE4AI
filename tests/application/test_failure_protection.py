import pytest

from rflp_lite.adapters.sqlite_repository import SQLiteRepository
from rflp_lite.application.demo import run_demo
from rflp_lite.domain.errors import AdapterFailure
from rflp_lite.governance.profile import Profile


class BrokenSolver:
    def solve(self, elements, profile):
        raise RuntimeError("injected solver failure")


def test_solver_failure_preserves_existing_baseline(tmp_path):
    successful = run_demo(tmp_path, Profile())
    with pytest.raises(AdapterFailure, match="injected solver failure"):
        run_demo(tmp_path, Profile(), solver_override=BrokenSolver())
    repository = SQLiteRepository(tmp_path / ".rflp" / "model.db")
    try:
        assert repository.latest_baseline().hash == successful.baseline.hash
        assert len(repository.audit_events("run.failed")) == 1
    finally:
        repository.close()

