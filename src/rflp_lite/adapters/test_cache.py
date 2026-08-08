from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from rflp_lite.adapters.project_scanner import (
    MAX_DEPTH,
    MAX_FILE_BYTES,
    MAX_FILES,
    SCAN_SUFFIXES,
    SKIP_DIRS,
)
from rflp_lite.adapters.test_execution_config import ResourceLimits, normalized_limits
from rflp_lite.adapters.execution_types import RunnerResult
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.domain.models import Evidence


CACHE_VERSION = 1


def _eligible_files(root: Path) -> tuple[Path, ...]:
    selected: list[Path] = []

    def walk(directory: Path, depth: int) -> None:
        if depth > MAX_DEPTH or len(selected) >= MAX_FILES:
            return
        for entry in sorted(directory.iterdir(), key=lambda item: item.name):
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name in SKIP_DIRS or entry.name.startswith("."):
                    continue
                walk(entry, depth + 1)
                if len(selected) >= MAX_FILES:
                    return
                continue
            if (
                entry.is_file()
                and entry.suffix.lower() in SCAN_SUFFIXES
                and depth + 1 <= MAX_DEPTH
                and entry.stat().st_size <= MAX_FILE_BYTES
            ):
                selected.append(entry)
                if len(selected) >= MAX_FILES:
                    return

    walk(root, 0)
    return tuple(selected)


def project_fingerprint(project_dir: Path) -> str:
    resolved = Path(project_dir).expanduser().resolve()
    if not resolved.is_dir():
        raise ContractViolation("项目目录不存在或不是目录")
    entries = tuple(
        (
            path.relative_to(resolved).as_posix(),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in _eligible_files(resolved)
    )
    return canonical_hash(entries)


def cache_key(project_dir: Path, runner: str, limits: ResourceLimits) -> str:
    return canonical_hash(
        {
            "project_fingerprint": project_fingerprint(project_dir),
            "runner": runner,
            "limits": normalized_limits(limits),
        }
    )


def _evidence_from_dict(value: dict[str, object]) -> Evidence:
    details = tuple((str(key), item) for key, item in value.get("details", ()))
    return Evidence(
        id=str(value["id"]),
        kind=str(value["kind"]),
        source=str(value["source"]),
        target_id=str(value["target_id"]),
        status=str(value["status"]),
        artifact_hash=str(value["artifact_hash"]),
        details=details,
    )


def load_cached_result(
    cache_dir: Path, key: str, runner: str
) -> RunnerResult | None:
    path = Path(cache_dir) / f"{key}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != CACHE_VERSION or data.get("runner") != runner:
            return None
        evidence = tuple(
            _evidence_from_dict(item)
            for item in data.get("evidence", ())
            if isinstance(item, dict)
        )
        return RunnerResult(
            runner=runner,
            command=tuple(str(item) for item in data.get("command", (runner,))),
            returncode=int(data["returncode"]),
            timed_out=bool(data["timed_out"]),
            junit_path=None,
            stdout_path=None,
            stderr_path=None,
            temp_dir=None,
            evidence=evidence,
            diagnostics=dict(data.get("diagnostics", {})),
            resource_limits=dict(data.get("resource_limits", {})),
            cache_hit=True,
        )
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
        return None


def save_cached_result(cache_dir: Path, key: str, result: RunnerResult) -> None:
    if result.returncode is None or result.timed_out:
        return
    target_dir = Path(cache_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{key}.json"
    command = tuple(
        "<temp>/junit.xml" if item.endswith("/junit.xml") else item
        for item in result.command
    )
    payload = {
        "version": CACHE_VERSION,
        "runner": result.runner,
        "command": command,
        "returncode": result.returncode,
        "timed_out": result.timed_out,
        "diagnostics": result.diagnostics,
        "resource_limits": result.resource_limits,
        "evidence": [asdict(item) for item in result.evidence],
    }
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{key}-", suffix=".tmp", dir=target_dir
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
