"""Use Case for generating an RFLP revision from reviewed requirements."""

from __future__ import annotations

from dataclasses import dataclass

from rflp_lite.application.use_cases.dependencies import GenerateRflpDeps
from rflp_lite.domain.errors import ContractViolation


@dataclass(frozen=True, slots=True)
class GenerateRflpCommand:
    state: dict[str, object]


class GenerateRflpUseCase:
    def __init__(self, dependencies: GenerateRflpDeps):
        self.dependencies = dependencies

    def execute(self, command: GenerateRflpCommand) -> dict[str, object]:
        if not command.state:
            raise ContractViolation("requirements workbench is empty")
        return self.dependencies.generator(command.state)


__all__ = ["GenerateRflpCommand", "GenerateRflpUseCase"]
