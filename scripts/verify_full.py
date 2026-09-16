"""Run the supported local verification matrix for AI4MBSE Harness."""

from __future__ import annotations

import subprocess
import sys
import os
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(*command: str, env: dict[str, str] | None = None) -> None:
    print("$", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True, env=env)


def main() -> int:
    python = sys.executable
    env = os.environ.copy()
    env.setdefault(
        "RFLP_CONFIG_DIR",
        tempfile.mkdtemp(prefix="ai4mbse-verify-config-"),
    )
    _run(python, "-m", "compileall", "-q", "src", env=env)
    _run(python, "-m", "pytest", "-q", env=env)
    _run(python, "scripts/architecture_metrics.py", env=env)
    _run(python, "-m", "ruff", "check", "src", "tests", "scripts", env=env)
    lint_imports = Path(python).with_name("lint-imports")
    _run(
        str(lint_imports) if lint_imports.is_file() else "lint-imports",
        env=env,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
