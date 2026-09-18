"""Application ownership of methodology runs and phase gates."""

from __future__ import annotations

from collections.abc import Mapping

from rflp_lite.application.input_preparation import InputPreparationResult, InputPreparationService
from rflp_lite.application.pipeline_report import PipelineReportService
from rflp_lite.methodology.contracts import Phase
from rflp_lite.methodology.gates import GateResult
from rflp_lite.methodology.workflow import RunSummary, WorkflowRunner


class AnalysisService:
    def __init__(
        self,
        runner: WorkflowRunner,
        *,
        input_preparation: InputPreparationService | None = None,
    ):
        self.runner = runner
        self.pipeline_reports = PipelineReportService(runner.model_repository)
        self.input_preparation = input_preparation or InputPreparationService(
            runner.model_repository,
            runner.runtime,
            runtime_selection=runner.runtime_selection,
        )

    def prepare_input(
        self,
        project_id: str,
        *,
        requirement_text: str | None = None,
        document_ids: tuple[str, ...] = (),
    ) -> InputPreparationResult:
        return self.input_preparation.prepare(
            project_id,
            requirement_text=requirement_text,
            document_ids=document_ids,
        )

    def run(
        self,
        project_id: str,
        phase: Phase | None = None,
        *,
        run_id: str | None = None,
        force_new: bool = False,
        new_run: bool = False,
        force_run: bool = False,
        requirement_text: str | None = None,
        document_ids: tuple[str, ...] = (),
    ) -> RunSummary:
        self.prepare_input(
            project_id,
            requirement_text=requirement_text,
            document_ids=document_ids,
        )
        return self.runner.run(
            project_id,
            phase,
            run_id=run_id,
            force_new=force_new,
            new_run=new_run,
            force_run=force_run,
        )

    def resume(self, project_id: str, run_id: str) -> RunSummary:
        return self.runner.resume(project_id, run_id)

    def run_pipeline(
        self,
        project_id: str,
        *,
        run_id: str | None = None,
        force_run: bool = False,
        requirement_text: str | None = None,
        document_ids: tuple[str, ...] = (),
    ) -> RunSummary:
        return self.run(
            project_id,
            None,
            run_id=run_id,
            force_run=force_run,
            requirement_text=requirement_text,
            document_ids=document_ids,
        )

    def pipeline_report(self, project_id: str) -> Mapping[str, object]:
        return self.pipeline_reports.build(project_id)

    def repair(self, project_id: str, issue_id: str) -> RunSummary:
        return self.runner.repair(project_id, issue_id)

    def gate(self, project_id: str, phase: Phase) -> GateResult:
        return self.runner.gate(project_id, phase)
