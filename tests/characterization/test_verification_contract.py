from pathlib import Path


def test_full_verification_script_lists_all_gates() -> None:
    script = Path("scripts/verify_full.py").read_text(encoding="utf-8")
    for command in (
        "compileall",
        "pytest",
        "lint-imports",
        "check-jsonschema",
        "ruff",
        "pyright",
        "build",
    ):
        assert command in script


def test_full_dependency_group_exists() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "test-full = [" in pyproject
    assert '"ruff>=0.9"' in pyproject
    assert '"pyright>=1.1"' in pyproject
