"""Application ownership of methodology runs and phase gates."""

from __future__ import annotations

from rflp_lite.methodology.contracts import Phase
from rflp_lite.methodology.gates import GateResult
from rflp_lite.methodology.workflow import RunSummary, WorkflowRunner


class AnalysisService:
    def __init__(self, runner: WorkflowRunner):
        self.runner = runner

    def run(self, project_id: str, phase: Phase | None = None) -> RunSummary:
        return self.runner.run(project_id, phase)

    def resume(self, project_id: str, run_id: str) -> RunSummary:
        return self.runner.resume(project_id, run_id)

    def repair(self, project_id: str, issue_id: str) -> RunSummary:
        return self.runner.repair(project_id, issue_id)

    def gate(self, project_id: str, phase: Phase) -> GateResult:
        return self.runner.gate(project_id, phase)
