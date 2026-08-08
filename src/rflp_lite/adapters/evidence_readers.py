from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import AdapterFailure
from rflp_lite.domain.models import Evidence


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_openapi(path: Path) -> tuple[Evidence, ...]:
    try:
        from prance.util.formats import parse_spec_details

        specification, _, _ = parse_spec_details(
            path.read_text(encoding="utf-8"), filename=path.name
        )
    except Exception as exc:
        raise AdapterFailure(f"OpenAPI parse failed: {path.name}: {exc}") from exc
    digest = _file_hash(path)
    results: list[Evidence] = []
    for route, path_item in sorted(specification.get("paths", {}).items()):
        for method, operation in sorted(path_item.items()):
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            operation_id = operation.get("operationId", f"{method}-{route}")
            evidence_id = f"evidence-{canonical_hash((digest, route, method, operation_id))[:12]}"
            results.append(
                Evidence(
                    id=evidence_id,
                    kind="openapi-operation",
                    source=f"{path.name}#{route}:{method}",
                    target_id=f"interface-{operation_id}",
                    status="observed",
                    artifact_hash=digest,
                    details=(("method", method.upper()), ("route", route)),
                )
            )
    return tuple(results)


def read_junit(path: Path, runner: str = "pytest") -> tuple[Evidence, ...]:
    try:
        from junitparser import JUnitXml

        document = JUnitXml.fromfile(str(path))
    except Exception as exc:
        raise AdapterFailure(f"JUnit parse failed: {path.name}: {exc}") from exc
    digest = _file_hash(path)
    results: list[Evidence] = []
    for suite in document:
        for case in suite:
            status = "passed" if not case.result else "failed"
            evidence_id = f"evidence-{canonical_hash((runner, digest, suite.name, case.name, status))[:12]}"
            results.append(
                Evidence(
                    id=evidence_id,
                    kind="test-case",
                    source=f"{path.name}#{suite.name}/{case.name}",
                    target_id=f"verification-{case.name}",
                    status=status,
                    artifact_hash=digest,
                    details=(("duration", float(case.time or 0.0)), ("runner", runner)),
                )
            )
    return tuple(results)


_UNITTEST_RESULT = re.compile(
    r"^(?P<display>.+?) \((?P<test_id>[^()]+)\) \.\.\. (?P<status>ok|FAIL|ERROR|skipped(?: \([^)]*\))?)$"
)


def read_unittest_output(path: Path) -> tuple[Evidence, ...]:
    """从 unittest -v 的稳定结果行派生测试证据。"""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise AdapterFailure(f"unittest 输出读取失败: {path.name}: {exc}") from exc
    parsed: list[tuple[str, str, str]] = []
    for line in lines:
        match = _UNITTEST_RESULT.match(line.strip())
        if match:
            status = match.group("status")
            normalized_status = (
                "passed"
                if status == "ok"
                else "failed"
                if status in {"FAIL", "ERROR"}
                else "skipped"
            )
            parsed.append(
                (match.group("test_id"), normalized_status, match.group("display"))
            )
    normalized = tuple(sorted(parsed, key=lambda item: item[0]))
    digest = canonical_hash(("unittest", normalized))
    return tuple(
        Evidence(
            id=f"evidence-{canonical_hash((digest, test_id, status))[:12]}",
            kind="test-case",
            source=f"unittest#{test_id}",
            target_id=f"verification-{test_id}",
            status=status,
            artifact_hash=digest,
            details=(("runner", "unittest"), ("display", display)),
        )
        for test_id, status, display in normalized
    )


def read_python_ast(path: Path) -> tuple[Evidence, ...]:
    digest = _file_hash(path)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
    except SyntaxError as exc:
        raise AdapterFailure(f"Python AST parse failed: {path.name}:{exc.lineno}") from exc
    results: list[Evidence] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        kind = "class" if isinstance(node, ast.ClassDef) else "function"
        evidence_id = f"evidence-{canonical_hash((digest, kind, node.name, node.lineno))[:12]}"
        results.append(
            Evidence(
                id=evidence_id,
                kind=f"python-{kind}",
                source=f"{path.name}:{node.lineno}",
                target_id=f"implementation-{node.name}",
                status="observed",
                artifact_hash=digest,
                details=(("line", node.lineno),),
            )
        )
    return tuple(sorted(results, key=lambda item: item.id))
