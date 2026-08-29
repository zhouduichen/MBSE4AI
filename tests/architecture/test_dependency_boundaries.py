from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src" / "rflp_lite"


def _adapter_imports(root: Path) -> tuple[str, ...]:
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.Import):
                module = next(
                    (alias.name for alias in node.names if alias.name.startswith("rflp_lite.adapters")),
                    "",
                )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if not module.startswith("rflp_lite.adapters"):
                    module = ""
            if module:
                violations.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}: {module}")
    return tuple(violations)


def test_application_and_interface_do_not_import_concrete_adapters() -> None:
    violations = _adapter_imports(SOURCE_ROOT / "application") + _adapter_imports(
        SOURCE_ROOT / "interface"
    )
    assert not violations, "Application/Interface adapter imports:\n" + "\n".join(violations)


def test_adapters_do_not_import_application_modules() -> None:
    violations: list[str] = []
    for path in sorted((SOURCE_ROOT / "adapters").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.Import):
                module = next(
                    (alias.name for alias in node.names if alias.name.startswith("rflp_lite.application")),
                    "",
                )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if not module.startswith("rflp_lite.application"):
                    module = ""
            if module:
                violations.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}: {module}")
    assert not violations, "Adapter/application reverse imports:\n" + "\n".join(violations)


def test_bootstrap_is_the_only_composition_root() -> None:
    violations = _adapter_imports(SOURCE_ROOT / "bootstrap")
    assert not violations or all("bootstrap" in item for item in violations)


def test_new_use_cases_use_explicit_dependencies() -> None:
    use_cases = SOURCE_ROOT / "application" / "use_cases"
    source = "\n".join(path.read_text(encoding="utf-8") for path in use_cases.glob("*.py"))
    assert "require_dependencies(" not in source
    assert "rflp_lite.adapters" not in source


def test_web_routes_do_not_acquire_repositories_or_models() -> None:
    source = (SOURCE_ROOT / "interface" / "web" / "routes.py").read_text(encoding="utf-8")
    assert "require_dependencies(" not in source
    assert "SQLiteRepository" not in source
    assert "GenerativeModel" not in source
