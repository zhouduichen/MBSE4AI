from __future__ import annotations

import sys
from pathlib import Path

import pytest

from rflp_lite.adapters.evidence_readers import read_unittest_output
from rflp_lite.adapters.test_runners import runner_spec
from rflp_lite.domain.errors import ContractViolation


def test_unittest_runner_uses_current_interpreter():
    spec = runner_spec("unittest", Path("/tmp/junit.xml"))
    assert spec.argv[:3] == (sys.executable, "-m", "unittest")
    assert spec.output_kind == "unittest-verbose"


def test_pytest_runner_adds_junit_output(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("rflp_lite.adapters.test_runners.shutil.which", lambda _: "/bin/pytest")
    spec = runner_spec("pytest", tmp_path / "junit.xml")
    assert spec.argv == ("/bin/pytest", "--junitxml", str(tmp_path / "junit.xml"))


def test_unknown_runner_is_rejected(tmp_path: Path):
    with pytest.raises(ContractViolation):
        runner_spec("shell", tmp_path / "junit.xml")


def test_parse_unittest_verbose_output_is_stable(tmp_path: Path):
    output = tmp_path / "stdout.log"
    output.write_text(
        "test_b (pkg.Case.test_b) ... FAIL\n"
        "test_a (pkg.Case.test_a) ... ok\n"
        "\nRan 2 tests in 0.001s\n\nFAILED (failures=1)\n",
        encoding="utf-8",
    )
    evidence = read_unittest_output(output)
    assert [item.status for item in evidence] == ["passed", "failed"]
    assert [item.target_id for item in evidence] == [
        "verification-pkg.Case.test_a",
        "verification-pkg.Case.test_b",
    ]
