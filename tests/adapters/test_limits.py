from __future__ import annotations

from rflp_lite.adapters.test_execution_config import ResourceLimits
from rflp_lite.adapters.test_limits import make_preexec_fn, resource_report


def test_resource_report_is_structured_and_deterministic():
    report = resource_report(
        ResourceLimits(
            timeout_seconds=5,
            memory_bytes=64 * 1024 * 1024,
            max_open_files=64,
            max_output_bytes=8192,
        )
    )
    assert set(report) == {"requested", "applied", "unsupported"}
    assert report["requested"] == {
        "memory_bytes": 64 * 1024 * 1024,
        "max_open_files": 64,
    }
    assert report["applied"] == sorted(report["applied"])
    assert report["unsupported"] == sorted(report["unsupported"])


def test_preexec_hook_is_optional_callable():
    hook = make_preexec_fn(ResourceLimits())
    assert hook is None or callable(hook)
