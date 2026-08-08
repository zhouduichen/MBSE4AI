from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from rflp_lite.adapters.evidence_readers import read_junit, read_unittest_output
from rflp_lite.domain.errors import AdapterFailure, ContractViolation


@dataclass(frozen=True, slots=True)
class RunnerSpec:
    name: str
    argv: tuple[str, ...]
    output_kind: str


def runner_spec(name: str, junit_path: Path) -> RunnerSpec:
    if name == "pytest":
        pytest_bin = shutil.which("pytest")
        command = (
            (pytest_bin, "--junitxml", str(junit_path))
            if pytest_bin
            else (sys.executable, "-m", "pytest", "--junitxml", str(junit_path))
        )
        return RunnerSpec(name, tuple(command), "junit")
    if name == "unittest":
        return RunnerSpec(
            name,
            (sys.executable, "-m", "unittest", "discover", "-v"),
            "unittest-verbose",
        )
    raise ContractViolation("测试运行器只能是 pytest 或 unittest")


def parse_runner_evidence(
    spec: RunnerSpec,
    stdout_path: Path | None,
    junit_path: Path | None,
) -> tuple:
    try:
        if spec.output_kind == "junit" and junit_path is not None:
            return read_junit(junit_path, runner=spec.name)
        if spec.output_kind == "unittest-verbose" and stdout_path is not None:
            return read_unittest_output(stdout_path)
    except (OSError, ValueError) as exc:
        raise AdapterFailure(f"无法解析 {spec.name} 测试结果: {exc}") from exc
    return ()
