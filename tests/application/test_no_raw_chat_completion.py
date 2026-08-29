from __future__ import annotations

import ast
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "rflp_lite"


def test_application_has_no_raw_chat_completion_bypass() -> None:
    violations: list[str] = []
    for path in (SOURCE_ROOT / "application").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [alias.name for alias in node.names]
                if any(name == "chat_completion" for name in names):
                    violations.append(f"{path}:{node.lineno}")
            if isinstance(node, ast.Attribute) and node.attr == "chat_completion":
                violations.append(f"{path}:{node.lineno}")
    assert not violations, "raw chat_completion bypasses:\n" + "\n".join(violations)


def test_new_use_cases_do_not_use_global_dependency_locator() -> None:
    violations = []
    for path in (SOURCE_ROOT / "application" / "use_cases").glob("*.py"):
        if "require_dependencies(" in path.read_text(encoding="utf-8"):
            violations.append(str(path))
    assert not violations, "new use cases use require_dependencies:\n" + "\n".join(violations)
