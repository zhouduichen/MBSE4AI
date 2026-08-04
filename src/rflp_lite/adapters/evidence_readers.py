from __future__ import annotations

import ast
import hashlib
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


def read_junit(path: Path) -> tuple[Evidence, ...]:
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
            evidence_id = f"evidence-{canonical_hash((digest, suite.name, case.name, status))[:12]}"
            results.append(
                Evidence(
                    id=evidence_id,
                    kind="test-case",
                    source=f"{path.name}#{suite.name}/{case.name}",
                    target_id=f"verification-{case.name}",
                    status=status,
                    artifact_hash=digest,
                    details=(("duration", float(case.time or 0.0)),),
                )
            )
    return tuple(results)


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

