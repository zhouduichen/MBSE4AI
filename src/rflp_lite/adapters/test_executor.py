from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from threading import Thread
from xml.etree import ElementTree

from rflp_lite.domain.errors import AdapterFailure, ContractViolation


DEFAULT_TEST_TIMEOUT = 60
MAX_RUN_OUTPUT_BYTES = 5 * 1024 * 1024
_JUNIT_ATTRS = ("time", "timestamp", "hostname", "id")


@dataclass(frozen=True, slots=True)
class TestRun:
    junit_path: Path | None
    stdout_path: Path
    stderr_path: Path
    temp_dir: Path
    returncode: int | None
    timed_out: bool


def _pump(stream: object, path: Path, limit: int) -> None:
    """把 stdout/stderr 读入文件，最多保留 limit 字节，超出丢弃而不杀进程。"""
    with path.open("wb") as handle:
        written = 0
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            if written < limit:
                take = chunk[: limit - written]
                handle.write(take)
                written += len(take)


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
        try:
            process = subprocess.Popen(
                command,
                cwd=resolved,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError as exc:
            raise AdapterFailure("无法启动 pytest") from exc
        stdout_thread = Thread(
            target=_pump, args=(process.stdout, stdout_file, MAX_RUN_OUTPUT_BYTES)
        )
        stderr_thread = Thread(
            target=_pump, args=(process.stderr, stderr_file, MAX_RUN_OUTPUT_BYTES)
        )
        stdout_thread.start()
        stderr_thread.start()
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            timed_out = True
            returncode = process.returncode
        stdout_thread.join()
        stderr_thread.join()
        junit_path = junit if junit.is_file() else None
        if junit_path is not None:
            _normalize_junit(junit_path)
        return TestRun(junit_path, stdout_file, stderr_file, temp_dir, returncode, timed_out)
    except BaseException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise