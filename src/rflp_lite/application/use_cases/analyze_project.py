"""Use Case boundary for read-only project scanning."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rflp_lite.application.use_cases.dependencies import AnalyzeProjectDeps
from rflp_lite.domain.errors import ContractViolation


@dataclass(frozen=True, slots=True)
class AnalyzeProjectCommand:
    source: Path


class AnalyzeProjectUseCase:
    def __init__(self, dependencies: AnalyzeProjectDeps):
        self.dependencies = dependencies

    def execute(self, command: AnalyzeProjectCommand) -> tuple[object, dict[str, object]]:
        source = command.source.expanduser().resolve()
        if not source.exists() or not source.is_dir():
            raise ContractViolation("项目源目录不存在")
        return self.dependencies.project_analysis.scan(source)


__all__ = ["AnalyzeProjectCommand", "AnalyzeProjectUseCase"]
