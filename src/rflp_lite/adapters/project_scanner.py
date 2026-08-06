from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import AdapterFailure, ContractViolation
from rflp_lite.domain.models import ActualElement, ActualModel


MAX_FILES = 400
MAX_DEPTH = 6
MAX_FILE_BYTES = 1024 * 1024
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".hypothesis",
    "dist",
    "build",
    ".idea",
    ".vscode",
    "site-packages",
}
SCAN_SUFFIXES = {".py", ".json", ".xml"}
_HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
_JUNIT_ROOTS = {"testsuites", "testsuite"}


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _element_id(rel_posix: str, kind: str, name: str, locator: object) -> str:
    return f"actual-{canonical_hash((rel_posix, kind, name, locator))[:12]}"


def _parse_python(
    rel_posix: str, path: Path, digest: str
) -> tuple[tuple[ActualElement, ...], str | None]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return (), f"{rel_posix}: 不是 UTF-8 编码的 Python 文件"
    try:
        tree = ast.parse(text, filename=path.name)
    except SyntaxError as exc:
        return (), f"{rel_posix}: Python 语法错误（第 {exc.lineno} 行）"
    module_name = Path(rel_posix).with_suffix("").as_posix()
    elements = [
        ActualElement(
            id=_element_id(rel_posix, "module", module_name, 0),
            kind="module",
            name=module_name,
            source=rel_posix,
            artifact_hash=digest,
        )
    ]
    for node in ast.walk(tree):
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        kind = "class" if isinstance(node, ast.ClassDef) else "function"
        elements.append(
            ActualElement(
                id=_element_id(rel_posix, kind, node.name, node.lineno),
                kind=kind,
                name=node.name,
                source=f"{rel_posix}:{node.lineno}",
                artifact_hash=digest,
                details=(("line", node.lineno),),
            )
        )
    return tuple(elements), None


def _parse_openapi(
    rel_posix: str, path: Path, digest: str
) -> tuple[tuple[ActualElement, ...], str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return (), f"{rel_posix}: JSON 解析失败（{exc}）"
    if not isinstance(data, dict) or not ("openapi" in data or "swagger" in data):
        return (), None
    paths = data.get("paths")
    if not isinstance(paths, dict):
        paths = {}
    elements: list[ActualElement] = []
    for route, path_item in sorted(paths.items(), key=lambda pair: str(pair[0])):
        if not isinstance(path_item, dict):
            continue
        for method in sorted(path_item):
            operation = path_item[method]
            if method.lower() not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            operation_id = str(operation.get("operationId") or f"{method}-{route}")
            elements.append(
                ActualElement(
                    id=_element_id(rel_posix, "api-operation", operation_id, f"{method} {route}"),
                    kind="api-operation",
                    name=operation_id,
                    source=f"{rel_posix}#{route}:{method.upper()}",
                    artifact_hash=digest,
                    details=(("method", method.upper()), ("route", route)),
                )
            )
    return tuple(elements), None


def _parse_junit(
    rel_posix: str, path: Path, digest: str
) -> tuple[tuple[ActualElement, ...], str | None]:
    try:
        root_tag = ElementTree.fromstring(path.read_bytes()).tag
    except ElementTree.ParseError as exc:
        return (), f"{rel_posix}: XML 解析失败（{exc}）"
    if root_tag.rsplit("}", 1)[-1] not in _JUNIT_ROOTS:
        return (), None
    try:
        from junitparser import JUnitXml

        document = JUnitXml.fromfile(str(path))
    except Exception as exc:
        return (), f"{rel_posix}: JUnit 解析失败（{type(exc).__name__}）"
    elements: list[ActualElement] = []
    for suite in document:
        for case in suite:
            status = "passed" if not case.result else "failed"
            elements.append(
                ActualElement(
                    id=_element_id(rel_posix, "test-case", case.name, f"{suite.name}/{case.name}"),
                    kind="test-case",
                    name=case.name,
                    source=f"{rel_posix}#{suite.name}/{case.name}",
                    artifact_hash=digest,
                    status=status,
                    details=(
                        ("suite", suite.name or ""),
                        ("duration", float(case.time or 0.0)),
                    ),
                )
            )
    return tuple(elements), None


def _parse_file(
    root: Path, path: Path
) -> tuple[tuple[ActualElement, ...], str | None]:
    rel_posix = path.relative_to(root).as_posix()
    digest = _file_digest(path)
    suffix = path.suffix.lower()
    if suffix == ".py":
        return _parse_python(rel_posix, path, digest)
    if suffix == ".json":
        return _parse_openapi(rel_posix, path, digest)
    return _parse_junit(rel_posix, path, digest)


def _scan_directory(
    root: Path,
    directory: Path,
    depth: int,
    elements: list[ActualElement],
    parse_errors: list[str],
    counters: dict[str, int],
) -> None:
    for entry in sorted(directory.iterdir(), key=lambda item: item.name):
        if entry.is_symlink():
            continue
        if entry.is_dir():
            if entry.name in SKIP_DIRS or entry.name.startswith("."):
                continue
            if depth >= MAX_DEPTH:
                continue
            _scan_directory(root, entry, depth + 1, elements, parse_errors, counters)
            continue
        if not entry.is_file() or entry.suffix.lower() not in SCAN_SUFFIXES:
            continue
        counters["files_seen"] += 1
        if depth + 1 > MAX_DEPTH or counters["files_used"] >= MAX_FILES:
            counters["files_skipped_limit"] += 1
            continue
        if entry.stat().st_size > MAX_FILE_BYTES:
            counters["files_skipped_size"] += 1
            continue
        new_elements, error = _parse_file(root, entry)
        if error is not None:
            parse_errors.append(error)
            continue
        if new_elements:
            counters["files_used"] += 1
            elements.extend(new_elements)


def scan_project(root: Path) -> tuple[ActualModel, dict[str, object]]:
    """扫描本地目录并返回 ActualModel 与确定性扫描摘要。"""
    resolved = Path(root).expanduser().resolve()
    if not resolved.is_dir():
        raise ContractViolation("项目目录不存在或不是目录")
    elements: list[ActualElement] = []
    parse_errors: list[str] = []
    counters = {"files_seen": 0, "files_used": 0, "files_skipped_size": 0, "files_skipped_limit": 0}
    _scan_directory(resolved, resolved, 0, elements, parse_errors, counters)
    if not elements:
        raise AdapterFailure("项目里没有可解析的 Python、OpenAPI 或 JUnit 制品")
    ordered = tuple(sorted(elements, key=lambda item: item.id))
    digest = canonical_hash(ordered)
    model = ActualModel(
        id=f"actualmodel-{digest[:12]}",
        source_root=resolved.name,
        elements=ordered,
        hash=digest,
    )
    summary = {
        "files_seen": counters["files_seen"],
        "files_used": counters["files_used"],
        "files_skipped_size": counters["files_skipped_size"],
        "files_skipped_limit": counters["files_skipped_limit"],
        "parse_errors": tuple(sorted(parse_errors)),
    }
    return model, summary
