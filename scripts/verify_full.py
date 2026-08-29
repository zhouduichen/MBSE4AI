"""Run the complete local verification matrix for RFLP-Lite."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _executable(name: str) -> str:
    environment_executable = Path(sys.executable).with_name(name)
    if environment_executable.is_file():
        return str(environment_executable)
    resolved = shutil.which(name)
    if resolved is None:
        raise SystemExit(f"required verification executable not found: {name}")
    return resolved


def _run(command: list[str], env: dict[str, str]) -> None:
    print("$", " ".join(command), flush=True)
    try:
        subprocess.run(
            command,
            cwd=ROOT,
            check=True,
            env=env,
            timeout=float(env.get("RFLP_VERIFY_TIMEOUT_SECONDS", "300")),
        )
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(f"verification command timed out: {' '.join(command)}") from exc


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="rflp-verify-config-") as config_dir:
        env = dict(os.environ)
        env["RFLP_CONFIG_DIR"] = config_dir
        env.setdefault("RFLP_VERIFY_TIMEOUT_SECONDS", "300")
        for key in tuple(env):
            if key.startswith("RFLP_LLM_") or key in {
                "OPENAI_API_KEY",
                "AWS_ACCESS_KEY_ID",
                "AWS_SECRET_ACCESS_KEY",
                "GITHUB_TOKEN",
                "GH_TOKEN",
                "SSH_AUTH_SOCK",
            }:
                env.pop(key, None)
        _run([sys.executable, "-m", "compileall", "-q", "src"], env)
        _run([sys.executable, "-m", "pytest", "-q"], env)
        _run([_executable("lint-imports")], env)
        _run(
            [
                _executable("check-jsonschema"),
                "--schemafile",
                "schemas/profile.schema.json",
                "examples/profile.json",
            ],
            env,
        )
        _run([_executable("ruff"), "check", "."], env)
        _run([_executable("pyright")], env)
        _run([sys.executable, "-m", "build", "--no-isolation"], env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
