"""Use Case boundary for objective project test execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rflp_lite.application.use_cases.dependencies import RunProjectTestsDeps
from rflp_lite.domain.errors import ContractViolation


@dataclass(frozen=True, slots=True)
class RunProjectTestsCommand:
    source: Path
    runners: tuple[str, ...] = ("pytest",)
    limits: object | None = None
    cache_dir: Path | None = None
    jobs: int = 1


class RunProjectTestsUseCase:
    def __init__(self, dependencies: RunProjectTestsDeps):
        self.dependencies = dependencies

    def execute(self, command: RunProjectTestsCommand) -> tuple[object, ...]:
        source = command.source.expanduser().resolve()
        if not source.exists() or not source.is_dir():
            raise ContractViolation("项目源目录不存在")
        return self.dependencies.test_execution.run(
            source,
            runners=command.runners,
            limits=command.limits,
            cache_dir=command.cache_dir,
            jobs=command.jobs,
        )


__all__ = ["RunProjectTestsCommand", "RunProjectTestsUseCase"]
