from __future__ import annotations

from pathlib import Path

import pytest

from rflp_lite.adapters.test_execution_config import build_limits
from rflp_lite.adapters.test_executor import run_project_test_matrix
from rflp_lite.domain.errors import ContractViolation


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "test_pytest.py").write_text(
        "def test_pytest_passes():\n    assert True\n", encoding="utf-8"
    )
    (project / "test_unittest.py").write_text(
        "import unittest\n\n"
        "class Case(unittest.TestCase):\n"
        "    def test_unittest_passes(self):\n"
        "        self.assertTrue(True)\n",
        encoding="utf-8",
    )
    return project


def test_matrix_runs_selected_runners_in_parallel(tmp_path: Path):
    project = _make_project(tmp_path)
    results = run_project_test_matrix(
        project,
        runners=("pytest", "unittest"),
        limits=build_limits(timeout_seconds=120),
        jobs=2,
    )
    assert [item.runner for item in results] == ["pytest", "unittest"]
    assert all(item.returncode == 0 for item in results)
    assert any(item.evidence for item in results)
    for item in results:
        if item.temp_dir is not None:
            import shutil

            shutil.rmtree(item.temp_dir, ignore_errors=True)


def test_matrix_rejects_duplicate_runner(tmp_path: Path):
    with pytest.raises(ContractViolation):
        run_project_test_matrix(tmp_path, runners=("pytest", "pytest"))
