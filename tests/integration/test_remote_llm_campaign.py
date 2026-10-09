from __future__ import annotations

import json
from pathlib import Path
import sys

from scripts.remote_llm_campaign import (
    command_sha256,
    run_campaign,
    status_is_evidence_ready,
    write_status,
)


def _manifest(tmp_path: Path, command: list[str]) -> dict[str, object]:
    report = tmp_path / "reports" / "a_to_e_comparison.json"
    status = tmp_path / "campaign-status.json"
    return {
        "campaign_id": "campaign-test",
        "run_id": "run-test",
        "profile": "test-profile",
        "comparison_mode": "natural",
        "command": command,
        "cwd": str(tmp_path),
        "results_dir": str(tmp_path / "results"),
        "reports_dir": str(report.parent),
        "comparison_report": str(report),
        "campaign_root": str(tmp_path),
        "status_path": str(status),
        "stdout_path": str(tmp_path / "campaign.stdout.log"),
        "stderr_path": str(tmp_path / "campaign.stderr.log"),
    }


def test_status_is_evidence_ready_requires_complete_pass_report(tmp_path: Path) -> None:
    status = {
        "state": "completed",
        "exit_code": 0,
        "comparison_report": str(tmp_path / "report.json"),
    }
    (tmp_path / "report.json").write_text(
        json.dumps({"status": "PASS", "execution_complete": True, "invariant_failures": []}),
        encoding="utf-8",
    )

    assert status_is_evidence_ready(status)
    status["state"] = "failed"
    assert not status_is_evidence_ready(status)


def test_write_status_replaces_json_atomically(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "status.json"
    write_status(path, {"state": "running", "attempt": 1})
    assert json.loads(path.read_text(encoding="utf-8")) == {"attempt": 1, "state": "running"}
    assert not list(path.parent.glob(".status.json.tmp.*"))


def test_run_campaign_records_terminal_failure_for_non_pass_report(tmp_path: Path) -> None:
    report_path = tmp_path / "reports" / "a_to_e_comparison.json"
    code = (
        "from pathlib import Path; import json; "
        f"p=Path({str(report_path)!r}); p.parent.mkdir(parents=True, exist_ok=True); "
        "p.write_text(json.dumps({'status': 'FAIL', 'execution_complete': False}), encoding='utf-8')"
    )
    manifest_path = tmp_path / "manifest.json"
    manifest = _manifest(tmp_path, [sys.executable, "-c", code])
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = run_campaign(manifest_path)

    assert result["state"] == "failed"
    assert result["exit_code"] == 0
    assert result["evidence_ready"] is False
    assert "comparison status" in str(result["error"])
    saved = json.loads(Path(str(manifest["status_path"])).read_text(encoding="utf-8"))
    assert saved["command_sha256"] == command_sha256(manifest["command"])


def test_run_campaign_requires_pass_report_for_success(tmp_path: Path) -> None:
    report_path = tmp_path / "reports" / "a_to_e_comparison.json"
    code = (
        "from pathlib import Path; import json; "
        f"p=Path({str(report_path)!r}); p.parent.mkdir(parents=True, exist_ok=True); "
        "p.write_text(json.dumps({'status': 'PASS', 'execution_complete': True, 'invariant_failures': []}), encoding='utf-8')"
    )
    manifest_path = tmp_path / "manifest.json"
    manifest = _manifest(tmp_path, [sys.executable, "-c", code])
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = run_campaign(manifest_path)

    assert result["state"] == "completed"
    assert result["exit_code"] == 0
    assert result["evidence_ready"] is True


def test_run_campaign_rejects_paths_outside_campaign_root(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, [sys.executable, "-c", "pass"])
    manifest["status_path"] = str(tmp_path.parent / "outside-status.json")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    try:
        run_campaign(manifest_path)
    except ValueError as exc:
        assert "status_path" in str(exc)
    else:
        raise AssertionError("campaign paths outside campaign_root must be rejected")
