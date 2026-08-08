from __future__ import annotations

from dataclasses import asdict, dataclass

from rflp_lite.domain.errors import ContractViolation


RUNNER_NAMES = ("pytest", "unittest")
DEFAULT_TEST_TIMEOUT = 60
DEFAULT_MEMORY_MIB = 1024
DEFAULT_MAX_OPEN_FILES = 1024
DEFAULT_MAX_OUTPUT_BYTES = 5 * 1024 * 1024
MIN_OUTPUT_BYTES = 8 * 1024
MAX_OUTPUT_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    timeout_seconds: int = DEFAULT_TEST_TIMEOUT
    memory_bytes: int | None = DEFAULT_MEMORY_MIB * 1024 * 1024
    max_open_files: int | None = DEFAULT_MAX_OPEN_FILES
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES


DEFAULT_RESOURCE_LIMITS = ResourceLimits()


def build_limits(
    *,
    timeout_seconds: int = DEFAULT_TEST_TIMEOUT,
    memory_mib: int | None = DEFAULT_MEMORY_MIB,
    max_open_files: int | None = DEFAULT_MAX_OPEN_FILES,
    output_mib: int = 5,
) -> ResourceLimits:
    if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool):
        raise ContractViolation("timeout 必须是整数")
    if not 1 <= timeout_seconds <= 3600:
        raise ContractViolation("timeout 必须在 1 到 3600 秒之间")
    if memory_mib is not None:
        if (
            not isinstance(memory_mib, int)
            or isinstance(memory_mib, bool)
            or (memory_mib != 0 and memory_mib < 64)
        ):
            raise ContractViolation("memory-mib 必须为 0 或不小于 64 MiB")
    if max_open_files is not None:
        if (
            not isinstance(max_open_files, int)
            or isinstance(max_open_files, bool)
            or (max_open_files != 0 and max_open_files < 16)
        ):
            raise ContractViolation("max-open-files 必须为 0 或不小于 16")
    if not isinstance(output_mib, int) or isinstance(output_mib, bool):
        raise ContractViolation("output-mib 必须是整数")
    output_bytes = output_mib * 1024 * 1024
    if not MIN_OUTPUT_BYTES <= output_bytes <= MAX_OUTPUT_BYTES:
        raise ContractViolation("output-mib 必须在 1 到 64 MiB 之间")
    return ResourceLimits(
        timeout_seconds=timeout_seconds,
        memory_bytes=None if memory_mib == 0 else memory_mib * 1024 * 1024,
        max_open_files=None if max_open_files == 0 else max_open_files,
        max_output_bytes=output_bytes,
    )


def validate_runner_names(runners: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    values = tuple(runners)
    if not values:
        raise ContractViolation("至少选择一个测试运行器")
    if any(value not in RUNNER_NAMES for value in values):
        raise ContractViolation("测试运行器只能是 pytest 或 unittest")
    if len(set(values)) != len(values):
        raise ContractViolation("测试运行器不能重复选择")
    return values


def validate_jobs(jobs: int) -> int:
    if not isinstance(jobs, int) or isinstance(jobs, bool) or jobs < 1:
        raise ContractViolation("jobs 必须是不小于 1 的整数")
    if jobs > len(RUNNER_NAMES):
        raise ContractViolation("jobs 不能超过可用运行器数量")
    return jobs


def normalized_limits(limits: ResourceLimits) -> dict[str, object]:
    return asdict(limits)
