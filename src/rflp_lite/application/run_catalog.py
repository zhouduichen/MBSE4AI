from __future__ import annotations

import json
import re
from pathlib import Path

from rflp_lite.domain.errors import ContractViolation
from rflp_lite.ports.tracking import TrackingRecord


RUN_OUTPUTS = (
    "artifacts.json",
    "spans.json",
    "claims.json",
    "rflp.json",
    "candidates.json",
    "decision.json",
    "simulation.json",
    "baseline.json",
    "delta.json",
    "task-contracts.json",
    "evidence.json",
    "run-manifest.json",
)
_RESULT_HASH = re.compile(r"[0-9a-f]{64}\Z")


# Compatibility name retained for application and interface callers.
RunRecord = TrackingRecord


def load_run(workspace: Path, result_hash: str) -> RunRecord:
    if not _RESULT_HASH.fullmatch(result_hash):
        raise ContractViolation("invalid result hash")
    workspace_root = workspace.resolve()
    run_dir = (workspace_root / ".rflp" / "runs" / result_hash).resolve()
    expected_parent = (workspace_root / ".rflp" / "runs").resolve()
    if run_dir.parent != expected_parent:
        raise ContractViolation("run path escapes the workspace")
    manifest_path = run_dir / "run-manifest.json"
    if not manifest_path.is_file():
        raise ContractViolation(f"run not found: {result_hash}")
    outputs = {
        name: json.loads((run_dir / name).read_text(encoding="utf-8"))
        for name in RUN_OUTPUTS
        if (run_dir / name).is_file()
    }
    manifest = outputs.get("run-manifest.json")
    if not isinstance(manifest, dict) or manifest.get("result_hash") != result_hash:
        raise ContractViolation("run manifest hash does not match its directory")
    return RunRecord(
        result_hash=result_hash,
        run_dir=run_dir,
        manifest=manifest,
        outputs=outputs,
        modified_ns=manifest_path.stat().st_mtime_ns,
    )


def list_runs(workspace: Path) -> tuple[RunRecord, ...]:
    runs_root = workspace.resolve() / ".rflp" / "runs"
    if not runs_root.is_dir():
        return ()
    records = (
        load_run(workspace, path.name)
        for path in runs_root.iterdir()
        if path.is_dir() and _RESULT_HASH.fullmatch(path.name)
    )
    return tuple(
        sorted(records, key=lambda record: (record.modified_ns, record.result_hash), reverse=True)
    )


def registered_output(record: RunRecord, filename: str) -> Path:
    if filename not in RUN_OUTPUTS:
        raise ContractViolation("run output is not registered")
    path = (record.run_dir / filename).resolve()
    if path.parent != record.run_dir or not path.is_file():
        raise ContractViolation("run output is not available")
    return path
