from __future__ import annotations

import json
import os
from pathlib import Path

from scripts.controller_lease_readiness import assess_lease


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _controller(root: Path, *, expires_at: float = 200.0, gpus: list[int] | None = None) -> None:
    _write(
        root / ".controller-gpu-lease.json",
        {
            "allocated_gpus": gpus if gpus is not None else [0],
            "expires_at": expires_at,
            "state": "allocated_for_controller",
        },
    )


def test_assess_lease_accepts_unexpired_disjoint_worker_lease(tmp_path: Path) -> None:
    _controller(tmp_path)
    _write(tmp_path / ".h3-worker-gpu-lease.json", {"allocated_gpus": [1, 2, 3]})

    ready, message = assess_lease(tmp_path, now=100.0)

    assert ready
    assert message == "READY:controller_gpus=[0],worker_gpus=[1, 2, 3]"


def test_assess_lease_rejects_gpu_overlap(tmp_path: Path) -> None:
    _controller(tmp_path)
    _write(tmp_path / ".h3-worker-gpu-lease.json", {"allocated_gpus": [0, 1]})

    ready, message = assess_lease(tmp_path, now=100.0)

    assert not ready
    assert message == "WAIT:controller-worker-gpu-overlap=[0]"


def test_assess_lease_ignores_expired_worker_lease(tmp_path: Path) -> None:
    _controller(tmp_path)
    _write(
        tmp_path / ".h3-worker-gpu-lease.json",
        {
            "allocated_gpus": [0, 1, 2, 3],
            "created_at": 10.0,
            "expires_at": 20.0,
            "owner_pid": 999999999,
        },
    )

    ready, message = assess_lease(tmp_path, now=100.0)

    assert ready
    assert message == "READY:controller_gpus=[0],worker_gpus=[]"


def test_assess_lease_ignores_worker_lease_after_owner_exit(tmp_path: Path) -> None:
    _controller(tmp_path)
    _write(
        tmp_path / ".h3-worker-gpu-lease.json",
        {
            "allocated_gpus": [0],
            "created_at": 90.0,
            "expires_at": 200.0,
            "owner_pid": 999999999,
        },
    )

    ready, message = assess_lease(tmp_path, now=100.0)

    assert ready
    assert message == "READY:controller_gpus=[0],worker_gpus=[]"


def test_assess_lease_keeps_live_worker_overlap_blocked(tmp_path: Path) -> None:
    _controller(tmp_path)
    _write(
        tmp_path / ".h3-worker-gpu-lease.json",
        {
            "allocated_gpus": [0],
            "created_at": 90.0,
            "expires_at": 200.0,
            "owner_pid": os.getpid(),
        },
    )

    ready, message = assess_lease(tmp_path, now=100.0)

    assert not ready
    assert message == "WAIT:controller-worker-gpu-overlap=[0]"


def test_assess_lease_rejects_expired_controller(tmp_path: Path) -> None:
    _controller(tmp_path, expires_at=100.0)

    ready, message = assess_lease(tmp_path, now=100.0)

    assert not ready
    assert message == "WAIT:controller-lease-expired"


def test_assess_lease_rejects_handoff_and_release_markers(tmp_path: Path) -> None:
    _controller(tmp_path)
    (tmp_path / ".controller-handoff-hold.json").write_text("{}", encoding="utf-8")
    ready, message = assess_lease(tmp_path, now=100.0)
    assert not ready
    assert message == "WAIT:controller-handoff-hold"

    (tmp_path / ".controller-handoff-hold.json").unlink()
    (tmp_path / ".controller-release.json").write_text("{}", encoding="utf-8")
    ready, message = assess_lease(tmp_path, now=100.0)
    assert not ready
    assert message == "WAIT:controller-release"
