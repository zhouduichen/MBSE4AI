"""Use Case for generating an evidence-backed MBSE revision."""

from __future__ import annotations

from dataclasses import dataclass

from rflp_lite.application.use_cases.dependencies import GenerateMbseDeps
from rflp_lite.domain.errors import ContractViolation


@dataclass(frozen=True, slots=True)
class GenerateMbseCommand:
    state: dict[str, object]
    revision: int | None = None


class GenerateMbseUseCase:
    def __init__(self, dependencies: GenerateMbseDeps):
        self.dependencies = dependencies

    def execute(self, command: GenerateMbseCommand) -> dict[str, object]:
        if not command.state:
            raise ContractViolation("requirements workbench is empty")
        if command.revision is None:
            return self.dependencies.generator(command.state)
        return self.dependencies.generator(command.state, command.revision)


__all__ = ["GenerateMbseCommand", "GenerateMbseUseCase"]
