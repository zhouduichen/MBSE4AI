import shutil
from pathlib import Path
from xml.etree import ElementTree

import pytest

from rflp_lite.adapters.test_executor import run_project_tests
from rflp_lite.domain.errors import AdapterFailure, ContractViolation


def _make_project(tmp_path: Path, body: str = "def test_passes():\n    assert True\n") -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "test_ok.py").write_text(body, encoding="utf-8")
    return project


def test_run_project_tests_passing_suite(tmp_path: Path):
    project = _make_project(tmp_path)
    run = run_project_tests(project, timeout=120)
    try:
        assert run.returncode == 0
        assert run.junit_path is not None
        assert run.timed_out is False
        assert run.stdout_path.is_file()
        root = ElementTree.parse(run.junit_path).getroot()
        for element in root.iter():
            for attribute in ("time", "timestamp", "hostname", "id"):
                assert attribute not in element.attrib
    finally:
        shutil.rmtree(run.temp_dir, ignore_errors=True)


def test_run_project_tests_failing_suite_still_writes_junit(tmp_path: Path):
    project = _make_project(tmp_path, body="def test_fails():\n    assert False\n")
    run = run_project_tests(project, timeout=120)
    try:
        assert run.returncode != 0
        assert run.junit_path is not None
    finally:
        shutil.rmtree(run.temp_dir, ignore_errors=True)


def test_normalized_junit_is_deterministic(tmp_path: Path):
    project = _make_project(tmp_path)
    first = run_project_tests(project, timeout=120)
    second = run_project_tests(project, timeout=120)
    try:
        assert first.junit_path is not None
        assert second.junit_path is not None
        assert first.junit_path.read_bytes() == second.junit_path.read_bytes()
    finally:
        shutil.rmtree(first.temp_dir, ignore_errors=True)
        shutil.rmtree(second.temp_dir, ignore_errors=True)


def test_run_project_tests_times_out(tmp_path: Path):
    project = _make_project(
        tmp_path, body="import time\ndef test_slow():\n    time.sleep(30)\n"
    )
    run = run_project_tests(project, timeout=1)
    try:
        assert run.timed_out is True
        assert run.returncode is not None
    finally:
        shutil.rmtree(run.temp_dir, ignore_errors=True)


def test_run_project_tests_missing_directory(tmp_path: Path):
    with pytest.raises(ContractViolation, match="项目目录不存在或不是目录"):
        run_project_tests(tmp_path / "does-not-exist")


def test_run_project_tests_reports_missing_pytest(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("rflp_lite.adapters.test_executor.shutil.which", lambda _: None)
    monkeypatch.setattr(
        "rflp_lite.adapters.test_executor.sys.executable",
        str(tmp_path / "no-such-python"),
    )
    project = _make_project(tmp_path)
    with pytest.raises(AdapterFailure, match="无法启动 pytest"):
        run_project_tests(project, timeout=5)


def test_run_project_tests_caps_run_output(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("rflp_lite.adapters.test_executor.MAX_RUN_OUTPUT_BYTES", 8192)
    project = _make_project(
        tmp_path,
        body=(
            "def test_spam():\n"
            "    for _ in range(100000):\n"
            "        print('x' * 100)\n"
            "    assert False\n"
        ),
    )
    run = run_project_tests(project, timeout=120)
    try:
        assert run.returncode != 0
        assert run.stdout_path.stat().st_size <= 8192
        assert run.stderr_path.stat().st_size <= 8192
    finally:
        shutil.rmtree(run.temp_dir, ignore_errors=True)


def test_run_project_tests_does_not_inherit_llm_secret(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RFLP_LLM_API_KEY", "SECRET_SENTINEL")
    project = _make_project(
        tmp_path,
        body=(
            "import os\n"
            "def test_environment_isolated():\n"
            "    print(os.environ.get('RFLP_LLM_API_KEY', '<absent>'))\n"
            "    assert os.environ.get('RFLP_LLM_API_KEY') is None\n"
        ),
    )
    run = run_project_tests(project, timeout=120)
    try:
        assert run.returncode == 0
        assert "SECRET_SENTINEL" not in run.stdout_path.read_text(encoding="utf-8")
        assert "SECRET_SENTINEL" not in run.stderr_path.read_text(encoding="utf-8")
    finally:
        shutil.rmtree(run.temp_dir, ignore_errors=True)
