from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from rflp_lite.domain.errors import AdapterFailure, ContractViolation


DEFAULT_TEST_TIMEOUT = 60
_JUNIT_ATTRS = ("time", "timestamp", "hostname", "id")


@dataclass(frozen=True, slots=True)
class TestRun:
    junit_path: Path | None
    stdout_path: Path
    stderr_path: Path
    temp_dir: Path
    returncode: int | None
    timed_out: bool


def _normalize_junit(path: Path) -> None:
    """去掉计时/主机元数据并按名称排序 testcase，使相同测试结果字节级确定。"""
    tree = ElementTree.parse(path)
    root = tree.getroot()
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag in {"testsuite", "testcase"}:
            for attribute in _JUNIT_ATTRS:
                element.attrib.pop(attribute, None)
    if root.tag.rsplit("}", 1)[-1] == "testsuite":
        suites = [root]
    else:
        suites = [element for element in list(root) if element.tag.rsplit("}", 1)[-1] == "testsuite"]
    for suite in suites:
        cases = [
            child for child in list(suite) if child.tag.rsplit("}", 1)[-1] == "testcase"
        ]
        cases.sort(
            key=lambda child: (
                child.attrib.get("classname", ""),
                child.attrib.get("name", ""),
            )
        )
        for child in list(suite):
            suite.remove(child)
        for child in cases:
            suite.append(child)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def run_project_tests(
    project_dir: Path, timeout: int = DEFAULT_TEST_TIMEOUT
) -> TestRun:
    """在项目目录内运行固定 `pytest` 命令，超时隔离，产物写入临时目录。"""
    resolved = Path(project_dir).expanduser().resolve()
    if not resolved.is_dir():
        raise ContractViolation("项目目录不存在或不是目录")
    if timeout <= 0:
        timeout = DEFAULT_TEST_TIMEOUT
    temp_dir = Path(tempfile.mkdtemp(prefix="rflp-testrun-"))
    junit = temp_dir / "junit.xml"
    stdout_file = temp_dir / "stdout.log"
    stderr_file = temp_dir / "stderr.log"
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pytest_bin = shutil.which("pytest")
    command = (
        [pytest_bin, "--junitxml", str(junit)]
        if pytest_bin
        else [sys.executable, "-m", "pytest", "--junitxml", str(junit)]
    )
    timed_out = False
    returncode: int | None = None
    try:
        with stdout_file.open("wb") as out_f, stderr_file.open("wb") as err_f:
            try:
                process = subprocess.Popen(
                    command, cwd=resolved, stdout=out_f, stderr=err_f, env=env
                )
            except FileNotFoundError as exc:
                raise AdapterFailure("无法启动 pytest") from exc
            try:
                returncode = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                timed_out = True
                returncode = process.returncode
        junit_path = junit if junit.is_file() else None
        if junit_path is not None:
            _normalize_junit(junit_path)
        return TestRun(junit_path, stdout_file, stderr_file, temp_dir, returncode, timed_out)
    except BaseException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise