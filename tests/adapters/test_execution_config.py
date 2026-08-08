from __future__ import annotations

import pytest

from rflp_lite.adapters.test_execution_config import (
    build_limits,
    normalized_limits,
    validate_jobs,
    validate_runner_names,
)
from rflp_lite.domain.errors import ContractViolation


def test_build_limits_uses_safe_defaults():
    limits = build_limits()
    assert limits.timeout_seconds == 60
    assert limits.memory_bytes == 1024 * 1024 * 1024
    assert limits.max_open_files == 1024
    assert limits.max_output_bytes == 5 * 1024 * 1024


def test_build_limits_allows_zero_for_optional_hard_limits():
    limits = build_limits(memory_mib=0, max_open_files=0, output_mib=1)
    assert limits.memory_bytes is None
    assert limits.max_open_files is None
    assert limits.max_output_bytes == 1024 * 1024


def test_invalid_limits_and_runner_names_are_rejected():
    with pytest.raises(ContractViolation):
        build_limits(timeout_seconds=0)
    with pytest.raises(ContractViolation):
        build_limits(memory_mib=63)
    with pytest.raises(ContractViolation):
        build_limits(max_open_files=15)
    with pytest.raises(ContractViolation):
        build_limits(output_mib=65)
    with pytest.raises(ContractViolation):
        validate_runner_names(("shell",))
    with pytest.raises(ContractViolation):
        validate_runner_names(("pytest", "pytest"))
    with pytest.raises(ContractViolation):
        validate_jobs(0)


def test_normalized_limits_are_json_ready():
    assert normalized_limits(build_limits(memory_mib=0))["memory_bytes"] is None
