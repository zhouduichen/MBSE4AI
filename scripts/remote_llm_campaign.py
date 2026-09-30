#!/usr/bin/env python3
"""Run a remote benchmark as a detached, auditable campaign.

The wrapper intentionally owns only the benchmark child process and files in
the campaign directory.  It does not manage GPUs, vLLM, or scheduler lease
markers; those remain external prerequisites and failures are recorded as
campaign evidence rather than repaired by force.  A detached campaign keeps
its status and partial artifacts when the caller disconnects, but it does not
resume an interrupted benchmark or skip already completed repeats.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from typing import Any, Mapping


TERMINAL_STATES = frozenset({"completed", "failed", "interrupted"})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def command_sha256(command: list[str]) -> str:
    return hashlib.sha256(canonical_json(command).encode("utf-8")).hexdigest()


def write_status(path: Path, payload: Mapping[str, object]) -> None:
    """Atomically publish a status document in the campaign directory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    temporary.write_text(canonical_json(dict(payload)) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _campaign_path(root: Path, value: object, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"manifest {field} is required")
    path = Path(value).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"manifest {field} must stay below campaign_root") from exc
    return path


def _report_is_pass(report_path: Path) -> tuple[bool, str | None]:
    if not report_path.is_file():
        return False, f"comparison report is missing: {report_path}"
    try:
        report = read_json(report_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return False, f"comparison report is invalid: {exc}"
    if report.get("status") != "PASS":
        return False, f"comparison status is {report.get('status')!r}"
    if report.get("execution_complete") is not True:
        return False, "comparison execution_complete is not true"
    failures = report.get("invariant_failures")
    if failures not in ([], None):
        return False, f"comparison invariant failures: {failures!r}"
    return True, None


def status_is_evidence_ready(payload: Mapping[str, object]) -> bool:
    """Return true only when the campaign has a complete PASS report."""

    if payload.get("state") != "completed" or payload.get("exit_code") != 0:
        return False
    report_path = payload.get("comparison_report")
    if not isinstance(report_path, str) or not report_path:
        return False
    ready, _ = _report_is_pass(Path(report_path))
    return ready


def _base_status(manifest: Mapping[str, object]) -> dict[str, object]:
    command = manifest.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
        raise ValueError("manifest command must be a non-empty list of strings")
    status_path = manifest.get("status_path")
    if not isinstance(status_path, str) or not status_path:
        raise ValueError("manifest status_path is required")
    return {
        "campaign_id": manifest.get("campaign_id"),
        "run_id": manifest.get("run_id"),
        "profile": manifest.get("profile"),
        "comparison_mode": manifest.get("comparison_mode"),
        "command_sha256": command_sha256(command),
        "command": command,
        "cwd": manifest.get("cwd"),
        "results_dir": manifest.get("results_dir"),
        "reports_dir": manifest.get("reports_dir"),
        "comparison_report": manifest.get("comparison_report"),
        "status_path": status_path,
    }


def run_campaign(manifest_path: Path) -> dict[str, object]:
    """Run the manifest command and leave a terminal, auditable status."""

    manifest = read_json(manifest_path)
    campaign_root_value = manifest.get("campaign_root")
    if not isinstance(campaign_root_value, str) or not campaign_root_value:
        raise ValueError("manifest campaign_root is required")
    campaign_root = Path(campaign_root_value).resolve(strict=False)
    _campaign_path(campaign_root, str(manifest_path), "manifest_path")
    status = _base_status(manifest)
    status_path = _campaign_path(campaign_root, status["status_path"], "status_path")
    stdout_path = _campaign_path(
        campaign_root,
        manifest.get("stdout_path", status_path.with_suffix(".stdout.log")),
        "stdout_path",
    )
    stderr_path = _campaign_path(
        campaign_root,
        manifest.get("stderr_path", status_path.with_suffix(".stderr.log")),
        "stderr_path",
    )
    for field in ("results_dir", "reports_dir", "comparison_report", "cwd"):
        _campaign_path(campaign_root, manifest.get(field), field)
    command = [str(item) for item in manifest["command"]]
    cwd = manifest.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        raise ValueError("manifest cwd is required")
    manifest_env = manifest.get("env", {})
    if not isinstance(manifest_env, Mapping) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in manifest_env.items()
    ):
        raise ValueError("manifest env must be a string-to-string object")

    child: subprocess.Popen[bytes] | None = None
    interrupted = False

    def handle_signal(signum: int, _frame: object) -> None:
        nonlocal interrupted
        interrupted = True
        if child is not None and child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass

    previous_int = signal.signal(signal.SIGINT, handle_signal)
    previous_term = signal.signal(signal.SIGTERM, handle_signal)
    started_at = utc_now()
    running = {
        **status,
        "state": "running",
        "created_at": manifest.get("created_at", started_at),
        "started_at": started_at,
        "finished_at": None,
        "pid": os.getpid(),
        "exit_code": None,
        "error": None,
    }
    write_status(status_path, running)
    try:
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
            child = subprocess.Popen(
                command,
                cwd=cwd,
                env={**os.environ, **dict(manifest_env)},
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            running["child_pid"] = child.pid
            write_status(status_path, running)
            exit_code = child.wait()
    except Exception as exc:
        exit_code = 1
        running["error"] = f"campaign wrapper error: {type(exc).__name__}: {exc}"
    finally:
        signal.signal(signal.SIGINT, previous_int)
        signal.signal(signal.SIGTERM, previous_term)

    finished_at = utc_now()
    if interrupted:
        state = "interrupted"
        error = "campaign wrapper received a termination signal"
    elif exit_code != 0:
        state = "failed"
        error = running.get("error") or f"benchmark exited with code {exit_code}"
    else:
        ready, report_error = _report_is_pass(Path(str(status["comparison_report"])))
        state = "completed" if ready else "failed"
        error = report_error
    terminal = {
        **running,
        "state": state,
        "finished_at": finished_at,
        "exit_code": int(exit_code),
        "error": error,
        "evidence_ready": state == "completed",
    }
    write_status(status_path, terminal)
    return terminal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--manifest", type=Path, required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == "run":
        result = run_campaign(args.manifest)
        print(canonical_json(result))
        return 0 if result.get("evidence_ready") else 1
    result = read_json(args.status)
    print(canonical_json(result))
    return 0 if status_is_evidence_ready(result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
