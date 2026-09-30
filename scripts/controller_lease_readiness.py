#!/usr/bin/env python3
"""Fail-closed readiness check for the remote Controller/vLLM lease."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from typing import Any, Mapping
from urllib.request import Request, urlopen


def _read_object(path: Path) -> Mapping[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def _gpu_set(value: object) -> set[int] | None:
    if not isinstance(value, list):
        return None
    result: set[int] = set()
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            return None
        result.add(item)
    return result


def assess_lease(state_root: Path, *, now: float | None = None) -> tuple[bool, str]:
    """Assess lease files without changing any remote state."""

    if (state_root / ".controller-handoff-hold.json").exists():
        return False, "WAIT:controller-handoff-hold"
    if (state_root / ".controller-release.json").exists():
        return False, "WAIT:controller-release"

    controller = _read_object(state_root / ".controller-gpu-lease.json")
    if controller is None:
        return False, "WAIT:controller-lease-missing-or-invalid"
    if controller.get("state") != "allocated_for_controller":
        return False, "WAIT:controller-lease-not-active"
    try:
        expires_at = float(controller["expires_at"])
    except (KeyError, TypeError, ValueError):
        return False, "WAIT:controller-lease-expiry-invalid"
    if expires_at <= (time.time() if now is None else float(now)):
        return False, "WAIT:controller-lease-expired"

    controller_gpus = _gpu_set(controller.get("allocated_gpus"))
    if controller_gpus is None or not controller_gpus:
        return False, "WAIT:controller-gpu-set-invalid"

    worker_path = state_root / ".h3-worker-gpu-lease.json"
    worker = _read_object(worker_path) if worker_path.exists() else {}
    if worker is None:
        return False, "WAIT:worker-lease-invalid"
    worker_gpus = _gpu_set(worker.get("allocated_gpus", []))
    if worker_gpus is None:
        return False, "WAIT:worker-gpu-set-invalid"
    overlap = sorted(controller_gpus & worker_gpus)
    if overlap:
        return False, f"WAIT:controller-worker-gpu-overlap={overlap}"
    return (
        True,
        "READY:controller_gpus="
        f"{sorted(controller_gpus)},worker_gpus={sorted(worker_gpus)}",
    )


def endpoint_ready(endpoint: str, *, timeout_seconds: float = 3.0) -> bool:
    request = Request(endpoint, method="GET")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return 200 <= int(response.status) < 400
    except (OSError, ValueError):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args(argv)
    if not endpoint_ready(args.endpoint, timeout_seconds=args.timeout):
        print("WAIT:vllm-endpoint-unavailable")
        return 1
    ready, message = assess_lease(args.state_root)
    print(message)
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
