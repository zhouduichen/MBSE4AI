"""Use Case for persisting objective evidence without changing semantics."""

from __future__ import annotations

from dataclasses import dataclass

from rflp_lite.application.use_cases.dependencies import RecordEvidenceDeps
from rflp_lite.domain.errors import ContractViolation


@dataclass(frozen=True, slots=True)
class RecordEvidenceCommand:
    state: dict[str, object]
    evidence: tuple[dict[str, object], ...]


class RecordEvidenceUseCase:
    def __init__(self, dependencies: RecordEvidenceDeps):
        self.dependencies = dependencies

    def execute(self, command: RecordEvidenceCommand) -> dict[str, object]:
        if not command.state:
            raise ContractViolation("requirements workbench is empty")
        return self.dependencies.recorder(command.state, command.evidence)


__all__ = ["RecordEvidenceCommand", "RecordEvidenceUseCase"]
