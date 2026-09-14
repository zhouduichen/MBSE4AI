"""Application ownership of methodology runs and phase gates."""

from __future__ import annotations

from collections.abc import Mapping

from rflp_lite.application.pipeline_report import PipelineReportService
from rflp_lite.methodology.contracts import Phase
from rflp_lite.methodology.gates import GateResult
from rflp_lite.methodology.workflow import RunSummary, WorkflowRunner


class AnalysisService:
    def __init__(self, runner: WorkflowRunner):
        self.runner = runner
        self.pipeline_reports = PipelineReportService(runner.model_repository)

    def run(
        self,
        project_id: str,
        phase: Phase | None = None,
        *,
        force_new: bool = False,
        new_run: bool = False,
        force_run: bool = False,
    ) -> RunSummary:
        return self.runner.run(
            project_id, phase, force_new=force_new, new_run=new_run, force_run=force_run
        )

    def resume(self, project_id: str, run_id: str) -> RunSummary:
        return self.runner.resume(project_id, run_id)

    def run_pipeline(self, project_id: str, *, run_id: str | None = None, force_run: bool = False) -> RunSummary:
        return self.runner.run(project_id, None, run_id=run_id, force_run=force_run)

    def pipeline_report(self, project_id: str) -> Mapping[str, object]:
        return self.pipeline_reports.build(project_id)

    def repair(self, project_id: str, issue_id: str) -> RunSummary:
        return self.runner.repair(project_id, issue_id)

    def gate(self, project_id: str, phase: Phase) -> GateResult:
        return self.runner.gate(project_id, phase)
