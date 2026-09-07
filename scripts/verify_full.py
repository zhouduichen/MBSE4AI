"""Run the supported local verification matrix for AI4MBSE Harness."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(*command: str) -> None:
    print("$", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    python = sys.executable
    _run(python, "-m", "compileall", "-q", "src")
    _run(python, "-m", "pytest", "-q")
    _run(python, "scripts/architecture_metrics.py")
    _run(python, "-m", "ruff", "check", "src", "tests", "scripts")
    lint_imports = Path(python).with_name("lint-imports")
    _run(str(lint_imports) if lint_imports.is_file() else "lint-imports")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
