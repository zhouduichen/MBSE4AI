from __future__ import annotations

from pathlib import Path
import shutil

from rflp_lite.adapters.execution_types import RunnerResult
from rflp_lite.adapters.test_cache import (
    cache_key,
    load_cached_result,
    project_fingerprint,
    save_cached_result,
)
from rflp_lite.adapters.test_execution_config import build_limits
from rflp_lite.adapters.test_executor import run_project_tests
from rflp_lite.domain.models import Evidence


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "test_ok.py").write_text(
        "def test_passes():\n    assert True\n", encoding="utf-8"
    )
    return project


def _result() -> RunnerResult:
    evidence = Evidence(
        id="evidence-1",
        kind="test-case",
        source="junit.xml#suite/test_passes",
        target_id="verification-test_passes",
        status="passed",
        artifact_hash="a" * 64,
    )
    return RunnerResult(
        runner="pytest",
        command=("pytest", "--junitxml", "/tmp/junit.xml"),
        returncode=0,
        timed_out=False,
        junit_path=Path("/tmp/junit.xml"),
        stdout_path=Path("/tmp/stdout.log"),
        stderr_path=Path("/tmp/stderr.log"),
        temp_dir=Path("/tmp/run"),
        evidence=(evidence,),
        diagnostics={"tests_passed": 1, "tests_failed": 0},
        resource_limits={"requested": {}, "applied": [], "unsupported": []},
    )


def test_cache_hit_requires_same_project_and_limits(tmp_path: Path):
    project = _make_project(tmp_path)
    first_key = cache_key(project, "pytest", build_limits())
    (project / "test_ok.py").write_text(
        "def test_changed():\n    assert True\n", encoding="utf-8"
    )
    second_key = cache_key(project, "pytest", build_limits())
    assert first_key != second_key


def test_save_and_load_cache_round_trip(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    save_cached_result(cache_dir, "abc", _result())
    loaded = load_cached_result(cache_dir, "abc", "pytest")
    assert loaded is not None
    assert loaded.cache_hit is True
    assert loaded.temp_dir is None
    assert loaded.evidence[0].target_id == "verification-test_passes"


def test_corrupt_cache_is_ignored(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "abc.json").write_text("not-json", encoding="utf-8")
    assert load_cached_result(cache_dir, "abc", "pytest") is None


def test_project_fingerprint_is_deterministic(tmp_path: Path):
    project = _make_project(tmp_path)
    assert project_fingerprint(project) == project_fingerprint(project)


def test_executor_uses_cached_completed_result(tmp_path: Path):
    project = _make_project(tmp_path)
    cache_dir = tmp_path / "cache"
    first = run_project_tests(project, timeout=120, cache_dir=cache_dir)
    second = run_project_tests(project, timeout=120, cache_dir=cache_dir)
    try:
        assert first.cache_hit is False
        assert second.cache_hit is True
        assert second.returncode == first.returncode == 0
        assert second.evidence == first.evidence
    finally:
        if first.temp_dir is not None:
            shutil.rmtree(first.temp_dir, ignore_errors=True)
