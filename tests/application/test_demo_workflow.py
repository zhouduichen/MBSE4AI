from pathlib import Path

from rflp_lite.application.demo import run_demo
from rflp_lite.governance.profile import Profile


def test_demo_runs_complete_chain(tmp_path):
    result = run_demo(tmp_path, Profile())
    assert len(result.claims) == 3
    assert len(result.candidates) >= 2
    assert result.baseline.status == "approved"
    assert result.simulation.passed
    assert result.delta.items
    assert result.task_contracts
    assert result.evidence
    assert Path(result.manifest_path).is_file()


def test_demo_is_reproducible_across_workspaces(tmp_path):
    first = run_demo(tmp_path / "first", Profile())
    second = run_demo(tmp_path / "second", Profile())
    assert first.result_hash == second.result_hash
    assert first.baseline.hash == second.baseline.hash

