from __future__ import annotations

import os
from collections.abc import Callable

from rflp_lite.adapters.test_execution_config import ResourceLimits

try:
    import resource as _resource
except ImportError:  # pragma: no cover - exercised on Windows only
    _resource = None


def resource_report(limits: ResourceLimits) -> dict[str, object]:
    requested: dict[str, int] = {}
    supported: list[str] = []
    if limits.memory_bytes is not None:
        requested["memory_bytes"] = limits.memory_bytes
        if _resource is not None and hasattr(_resource, "RLIMIT_AS"):
            supported.append("memory_bytes")
    if limits.max_open_files is not None:
        requested["max_open_files"] = limits.max_open_files
        if _resource is not None and hasattr(_resource, "RLIMIT_NOFILE"):
            supported.append("max_open_files")
    if _resource is not None and hasattr(_resource, "RLIMIT_CPU"):
        supported.append("cpu_seconds")
    return {
        "requested": requested,
        "applied": sorted(supported),
        "unsupported": sorted(set(requested) - set(supported)),
    }


def _bounded_limit(value: int, hard: int) -> int:
    if hard == _resource.RLIM_INFINITY:
        return value
    return min(value, hard)


def make_preexec_fn(limits: ResourceLimits) -> Callable[[], None] | None:
    if os.name != "posix" or _resource is None:
        return None

    def apply_limits() -> None:
        if limits.memory_bytes is not None and hasattr(_resource, "RLIMIT_AS"):
            try:
                _, hard = _resource.getrlimit(_resource.RLIMIT_AS)
                value = _bounded_limit(limits.memory_bytes, hard)
                _resource.setrlimit(_resource.RLIMIT_AS, (value, value))
            except (OSError, ValueError):
                pass
        if limits.max_open_files is not None and hasattr(_resource, "RLIMIT_NOFILE"):
            try:
                _, hard = _resource.getrlimit(_resource.RLIMIT_NOFILE)
                value = _bounded_limit(limits.max_open_files, hard)
                _resource.setrlimit(_resource.RLIMIT_NOFILE, (value, value))
            except (OSError, ValueError):
                pass
        if hasattr(_resource, "RLIMIT_CPU"):
            try:
                _, hard = _resource.getrlimit(_resource.RLIMIT_CPU)
                value = _bounded_limit(max(1, limits.timeout_seconds), hard)
                _resource.setrlimit(_resource.RLIMIT_CPU, (value, value))
            except (OSError, ValueError):
                pass

    return apply_limits
