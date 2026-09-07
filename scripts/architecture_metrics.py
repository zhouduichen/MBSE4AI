"""Deterministic architecture metrics used by the consolidation budget."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src" / "rflp_lite"
_DICT_PATTERN = re.compile(r"dict\s*\[\s*str\s*,\s*object\s*\]")
_REQUEST_JSON_PATTERN = re.compile(r"\brequest\s*\.\s*json\s*\(")


def _python_files(root: Path) -> tuple[Path, ...]:
    return tuple(sorted(root.rglob("*.py")))


def _absolute_imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return tuple(imports)


def _module_name(path: Path) -> str:
    relative = path.relative_to(SOURCE_ROOT).with_suffix("")
    parts = relative.parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return "rflp_lite." + ".".join(parts)


def _module_graph() -> dict[str, set[str]]:
    known = {_module_name(path) for path in _python_files(SOURCE_ROOT)}
    graph = {module: set() for module in known}
    for path in _python_files(SOURCE_ROOT):
        module = _module_name(path)
        for imported in _absolute_imports(path):
            candidate = imported
            while candidate and candidate not in known:
                candidate = candidate.rpartition(".")[0]
            if candidate in known and candidate != module:
                graph[module].add(candidate)
    return graph


def _strongly_connected_components(graph: dict[str, set[str]]) -> tuple[tuple[str, ...], ...]:
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for neighbor in sorted(graph[node]):
            if neighbor not in indices:
                visit(neighbor)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
            elif neighbor in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[neighbor])
        if lowlinks[node] == indices[node]:
            component: list[str] = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.append(member)
                if member == node:
                    break
            if len(component) > 1:
                components.append(tuple(sorted(component)))

    for node in sorted(graph):
        if node not in indices:
            visit(node)
    return tuple(sorted(components))


def _count_calls(name: str) -> int:
    count = 0
    for path in _python_files(SOURCE_ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        count += sum(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == name
            for node in ast.walk(tree)
        )
    return count


def _count_adapter_application_edges() -> int:
    count = 0
    adapter_root = SOURCE_ROOT / "adapters"
    for path in _python_files(adapter_root):
        count += sum(
            imported.startswith("rflp_lite.application")
            for imported in _absolute_imports(path)
        )
    return count


def _count_long_functions(limit: int = 150) -> int:
    count = 0
    for path in _python_files(SOURCE_ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        count += sum(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.end_lineno is not None
            and node.end_lineno - node.lineno + 1 > limit
            for node in ast.walk(tree)
        )
    return count


def measure() -> dict[str, int]:
    source_text = "\n".join(
        path.read_text(encoding="utf-8") for path in _python_files(SOURCE_ROOT)
    )
    facade_methods = 0
    facade_path = SOURCE_ROOT / "application" / "web_facade.py"
    if facade_path.exists():
        facade_tree = ast.parse(facade_path.read_text(encoding="utf-8"))
        for node in facade_tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "WebFacade":
                facade_methods = sum(
                    isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    for item in node.body
                )
                break
    return {
        "require_dependencies_calls": _count_calls("require_dependencies"),
        "adapter_to_application_edges": _count_adapter_application_edges(),
        "module_cycles": len(_strongly_connected_components(_module_graph())),
        "dict_str_object_occurrences": len(_DICT_PATTERN.findall(source_text)),
        "raw_request_json_calls": len(_REQUEST_JSON_PATTERN.findall(source_text)),
        "web_facade_methods": facade_methods,
        "functions_over_150_lines": _count_long_functions(),
    }


def load_budget(path: Path | None = None) -> dict[str, int]:
    budget_path = path or PROJECT_ROOT / "architecture_budget.json"
    return json.loads(budget_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    print(json.dumps(measure(), ensure_ascii=False, indent=2, sort_keys=True))
