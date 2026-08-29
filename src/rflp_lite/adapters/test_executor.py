from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Mapping
from pathlib import Path
from threading import Thread
from typing import IO
from xml.etree import ElementTree

from rflp_lite.adapters.test_execution_config import (
    DEFAULT_MAX_OUTPUT_BYTES,
    DEFAULT_RESOURCE_LIMITS,
    DEFAULT_TEST_TIMEOUT,
    ResourceLimits,
    validate_jobs,
    validate_runner_names,
)
from rflp_lite.adapters.test_cache import cache_key, load_cached_result, save_cached_result
from rflp_lite.adapters.execution_types import RunnerResult
from rflp_lite.adapters.test_limits import make_preexec_fn, resource_report
from rflp_lite.adapters.test_runners import parse_runner_evidence, runner_spec
from rflp_lite.domain.errors import AdapterFailure, ContractViolation


# Kept as a compatibility hook for existing callers/tests that cap this value.
MAX_RUN_OUTPUT_BYTES = DEFAULT_MAX_OUTPUT_BYTES
_JUNIT_ATTRS = ("time", "timestamp", "hostname", "id")


# Historical name retained for callers that imported the old result type.
TestRun = RunnerResult

_ENVIRONMENT_KEYS = ("PATH", "PYTHONPATH", "LANG")


def build_test_environment(
    run_root: Path,
    project_dir: Path,
    allowed: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a minimal child environment without inheriting credentials."""
    home = run_root / "home"
    temp = run_root / "tmp"
    output = run_root / "output"
    for path in (home, temp, output):
        path.mkdir(parents=True, exist_ok=True)
    environment = {
        key: os.environ[key]
        for key in _ENVIRONMENT_KEYS
        if os.environ.get(key)
    }
    environment.update(
        {
            "HOME": str(home),
            "TMPDIR": str(temp),
            "PYTHONDONTWRITEBYTECODE": "1",
            "RFLP_TEST_OUTPUT_DIR": str(output),
        }
    )
    if allowed:
        environment.update({str(key): str(value) for key, value in allowed.items()})
    environment.setdefault("PYTHONPATH", str(project_dir))
    return environment


def run_project_test_matrix(
    project_dir: Path,
    runners: tuple[str, ...] = ("pytest",),
    limits: ResourceLimits | None = None,
    cache_dir: Path | None = None,
    jobs: int = 1,
) -> tuple[RunnerResult, ...]:
    """运行一个受控 runner 集合；默认串行，结果按 runner 名称稳定排序。"""
    names = validate_runner_names(tuple(runners))
    validate_jobs(jobs)
    worker_count = min(jobs, len(names))

    def execute(name: str) -> RunnerResult:
        timeout = limits.timeout_seconds if limits is not None else DEFAULT_TEST_TIMEOUT
        return run_project_tests(
            project_dir,
            timeout=timeout,
            runner=name,
            limits=limits,
            cache_dir=cache_dir,
        )

    if worker_count == 1 or len(names) == 1:
        results = tuple(execute(name) for name in names)
    else:
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="rflp-test") as pool:
            results = tuple(pool.map(execute, names))
    return tuple(sorted(results, key=lambda item: item.runner))


def _pump(stream: IO[bytes], path: Path, limit: int) -> None:
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


def _tail(path: Path | None, max_lines: int = 15, max_chars: int = 2000) -> str:
    if path is None:
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-max_lines:]).strip()[:max_chars]


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
        suites = [
            element
            for element in list(root)
            if element.tag.rsplit("}", 1)[-1] == "testsuite"
        ]
    for suite in suites:
        cases = [
            child
            for child in list(suite)
            if child.tag.rsplit("}", 1)[-1] == "testcase"
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


def _limits_for_call(timeout: int, limits: ResourceLimits | None) -> ResourceLimits:
    if limits is not None:
        return limits
    timeout_seconds = DEFAULT_TEST_TIMEOUT if timeout <= 0 else timeout
    return ResourceLimits(
        timeout_seconds=timeout_seconds,
        memory_bytes=DEFAULT_RESOURCE_LIMITS.memory_bytes,
        max_open_files=DEFAULT_RESOURCE_LIMITS.max_open_files,
        max_output_bytes=MAX_RUN_OUTPUT_BYTES,
    )


def run_project_tests(
    project_dir: Path,
    timeout: int = DEFAULT_TEST_TIMEOUT,
    *,
    runner: str = "pytest",
    limits: ResourceLimits | None = None,
    cache_dir: Path | None = None,
) -> RunnerResult:
    """运行一个内置测试运行器，超时隔离，产物写入临时目录。"""
    resolved = Path(project_dir).expanduser().resolve()
    if not resolved.is_dir():
        raise ContractViolation("项目目录不存在或不是目录")
    effective_limits = _limits_for_call(timeout, limits)
    key = None
    if cache_dir is not None:
        key = cache_key(resolved, runner, effective_limits)
        cached = load_cached_result(cache_dir, key, runner)
        if cached is not None:
            return cached
    temp_dir = Path(tempfile.mkdtemp(prefix="rflp-testrun-"))
    junit = temp_dir / "junit.xml"
    stdout_file = temp_dir / "stdout.log"
    stderr_file = temp_dir / "stderr.log"
    spec = runner_spec(runner, junit)
    env = build_test_environment(temp_dir, resolved)
    timed_out = False
    returncode: int | None = None
    try:
        try:
            process = subprocess.Popen(
                spec.argv,
                cwd=resolved,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                shell=False,
                preexec_fn=make_preexec_fn(effective_limits),
            )
        except FileNotFoundError as exc:
            message = "无法启动 pytest" if runner == "pytest" else "无法启动 unittest"
            raise AdapterFailure(message) from exc
        assert process.stdout is not None
        assert process.stderr is not None
        stdout_thread = Thread(
            target=_pump,
            args=(process.stdout, stdout_file, effective_limits.max_output_bytes),
        )
        stderr_thread = Thread(
            target=_pump,
            args=(process.stderr, stderr_file, effective_limits.max_output_bytes),
        )
        stdout_thread.start()
        stderr_thread.start()
        try:
            returncode = process.wait(timeout=effective_limits.timeout_seconds)
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
        output_path = stderr_file if spec.output_kind == "unittest-verbose" else stdout_file
        evidence = parse_runner_evidence(spec, output_path, junit_path)
        failed_tests = sorted(
            item.target_id.removeprefix("verification-")
            for item in evidence
            if item.status == "failed"
        )
        diagnostics = {
            "stdout_tail": _tail(stdout_file),
            "stderr_tail": _tail(stderr_file),
            "failed_tests": failed_tests,
            "tests_passed": sum(1 for item in evidence if item.status == "passed"),
            "tests_failed": sum(1 for item in evidence if item.status == "failed"),
            "unparsed_output": runner == "unittest" and not evidence,
        }
        result = RunnerResult(
            runner=runner,
            command=spec.argv,
            returncode=returncode,
            timed_out=timed_out,
            junit_path=junit_path,
            stdout_path=stdout_file,
            stderr_path=stderr_file,
            temp_dir=temp_dir,
            evidence=tuple(sorted(evidence, key=lambda item: item.id)),
            diagnostics=diagnostics,
            resource_limits=resource_report(effective_limits),
        )
        if cache_dir is not None and key is not None:
            save_cached_result(cache_dir, key, result)
        return result
    except BaseException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
