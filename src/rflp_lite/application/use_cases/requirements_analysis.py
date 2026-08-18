"""Orchestration for requirement ingestion and incremental enrichment."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rflp_lite.application.intelligence.analysis_config import normalize_analysis_config
from rflp_lite.application.intelligence.enrichment_jobs import EnrichmentJobRunner
from rflp_lite.application.project_scope import (
    bind_project_scope,
    validate_project_references,
    validate_project_scope,
)
from rflp_lite.application.requirements_workbench import (
    accept_initial_workbench,
    generate_draft_model,
)
from rflp_lite.application.traceability import (
    build_trace_matrix,
    refresh_traceability,
    trace_coverage,
)
from rflp_lite.application.workspaces import WorkspaceRef
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.ports.generative_model import GenerativeModel
from rflp_lite.ports.jobs import JobServiceFactory
from rflp_lite.ports.repositories import RepositoryFactory


@dataclass(frozen=True, slots=True)
class RequirementsAnalysisDependencies:
    """Only the capabilities needed by the requirements-analysis use case."""

    repository_factory: RepositoryFactory
    job_service_factory: JobServiceFactory
    enrichment_runner_factory: Callable[[Path], EnrichmentJobRunner]
    load_state: Callable[[WorkspaceRef], dict[str, object] | None]
    analyze_artifact: Callable[[str, bytes], dict[str, object]]
    merge_artifact: Callable[
        [dict[str, object], str, bytes], dict[str, object]
    ]


class RequirementsAnalysisService:
    """Persist a requirements baseline and schedule its enrichment."""

    def __init__(self, dependencies: RequirementsAnalysisDependencies):
        self.dependencies = dependencies

    def analyze(
        self,
        workspace: WorkspaceRef,
        filename: str,
        content: bytes,
        *,
        merge: bool = True,
        model: GenerativeModel | None = None,
    ) -> dict[str, object]:
        safe_name = Path(filename).name
        current = self.dependencies.load_state(workspace)
        if merge and current is not None:
            state = self.dependencies.merge_artifact(current, safe_name, content)
        else:
            state = self.dependencies.analyze_artifact(safe_name, content)
            state = self._initialize_review_state(state)

        state = bind_project_scope(state, workspace.name)
        state["analysis_config"] = normalize_analysis_config(
            state.get("analysis_config")
        )
        if state.get("spans"):
            state = generate_draft_model(state)
            state = accept_initial_workbench(state)
            state["auto_analysis"] = {
                "status": "baseline_ready",
                "job_id": None,
                "input_hash": self._input_hash(state),
                "blocks": {},
                "diagnostics": [
                    {
                        "code": "baseline_ready",
                        "severity": "info",
                        "message": "规则和明确输入已先保存为 accepted 基线，LLM 补全将在后台分块执行。",
                    }
                ],
                "modules": {"baseline": True},
            }

        state = refresh_traceability(state)
        validate_project_scope(state, workspace.name)
        validate_project_references(state)
        inputs = workspace.path / "inputs"
        inputs.mkdir(parents=True, exist_ok=True)
        artifact = state.get("artifact") or {}
        (inputs / f'{artifact["sha256"][:12]}-{artifact["path"]}').write_bytes(content)

        event = "requirements.merged" if merge else "requirements.analyzed"
        self._save_initial(workspace, state, event)

        if not state.get("spans"):
            return state

        input_hash = self._input_hash(state)
        job = self.dependencies.enrichment_runner_factory(workspace.path).submit(
            model, input_hash=input_hash
        )
        latest = self.dependencies.load_state(workspace) or state
        job_status = str(job.get("status", ""))
        if job_status in {"queued", "running"}:
            latest["auto_analysis"] = {
                **dict(latest.get("auto_analysis") or {}),
                "status": "enriching",
                "job_id": job.get("id"),
                "blocks": dict(job.get("blocks") or {}),
            }
            return self._save_requirements(
                workspace,
                latest,
                "requirements.enrichment_queued",
                {"job_id": job.get("id"), "input_hash": input_hash},
            )

        job_result = job.get("result") if isinstance(job.get("result"), dict) else {}
        final_status = str(job_result.get("status", "")) or (
            "degraded" if job_status == "failed" else job_status
        )
        current_analysis = dict(latest.get("auto_analysis") or {})
        if not current_analysis.get("job_id") or current_analysis.get("status") in {
            "baseline_ready",
            "enriching",
        }:
            latest["auto_analysis"] = {
                **current_analysis,
                "status": final_status,
                "job_id": job.get("id"),
                "blocks": dict(
                    job.get("blocks") or current_analysis.get("blocks") or {}
                ),
                "diagnostics": list(current_analysis.get("diagnostics") or [])
                + ([job.get("error")] if isinstance(job.get("error"), dict) else []),
            }
            return self._save_requirements(
                workspace,
                latest,
                "requirements.enrichment_finished",
                {"job_id": job.get("id"), "status": final_status},
            )
        return latest

    def retry(
        self,
        workspace: WorkspaceRef,
        job_id: str,
        *,
        model: GenerativeModel | None = None,
    ) -> dict[str, object]:
        job_service = self.dependencies.job_service_factory(workspace.path)
        previous = job_service.get(job_id)
        if previous is None:
            raise ContractViolation("enrichment job not found")
        new_job = self.dependencies.enrichment_runner_factory(workspace.path).retry(
            job_id, model
        )
        current = self.dependencies.load_state(workspace)
        if current is not None:
            current["auto_analysis"] = {
                **dict(current.get("auto_analysis") or {}),
                "status": "enriching",
                "job_id": new_job.get("id"),
                "blocks": dict(new_job.get("blocks") or {}),
            }
            self._save_requirements(
                workspace,
                current,
                "requirements.enrichment_retry_queued",
                {"previous_job_id": job_id, "job_id": new_job.get("id")},
            )
        return new_job

    @staticmethod
    def _initialize_review_state(state: dict[str, object]) -> dict[str, object]:
        # Import locally to keep the use-case module's top-level dependency list
        # focused on orchestration and avoid a duplicate public import surface.
        from rflp_lite.application.requirements_workbench import initialize_review_state

        return initialize_review_state(state)

    @staticmethod
    def _input_hash(state: dict[str, object]) -> str:
        scope = state.get("project_scope")
        if isinstance(scope, dict):
            return str(scope.get("input_hash", ""))
        return ""

    def _save_initial(
        self, workspace: WorkspaceRef, state: dict[str, object], event: str
    ) -> None:
        repository = self.dependencies.repository_factory(
            workspace.path / ".rflp" / "model.db"
        )
        try:
            with repository.transaction():
                repository.save_workbench(state, event)
                sequence = repository.record_audit(
                    event,
                    {
                        "artifact": (state.get("artifact") or {}).get("path", ""),
                        "sha256": (state.get("artifact") or {}).get("sha256", ""),
                    },
                )
                repository.save_requirement_records(
                    self._requirement_records_for_state(state, event), sequence, event
                )
        finally:
            repository.close()

    def _save_requirements(
        self,
        workspace: WorkspaceRef,
        state: dict[str, object],
        event: str,
        audit_payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        scope = state.get("project_scope")
        if not isinstance(scope, dict) or not str(scope.get("workspace", "")):
            state = bind_project_scope(state, workspace.name)
        validate_project_scope(state, workspace.name)
        state = refresh_traceability(state)
        validate_project_references(state)
        repository = self.dependencies.repository_factory(
            workspace.path / ".rflp" / "model.db"
        )
        try:
            with repository.transaction():
                repository.save_workbench(state, event)
                sequence = repository.record_audit(
                    event,
                    audit_payload or {"artifact": (state.get("artifact") or {}).get("path", "")},
                )
                repository.save_requirement_records(
                    self._requirement_records_for_state(state, event), sequence, event
                )
                repository.save_trace_records(tuple(state.get("trace_links", ())))
                repository.record_audit(
                    "requirements.traceability_updated",
                    {
                        "coverage": state.get(
                            "trace_coverage", trace_coverage(build_trace_matrix(state))
                        )
                    },
                )
        finally:
            repository.close()
        return state

    @staticmethod
    def _requirement_records_for_state(
        state: dict[str, object], event: str
    ) -> tuple[dict[str, object], ...]:
        artifact = state.get("artifact") or {}
        spans = {str(item.get("id")): item for item in state.get("spans", ())}
        records = []
        for claim in state.get("claims", ()):
            span = spans.get(str(claim.get("span_id")), {})
            records.append(
                {
                    "id": str(claim["id"]),
                    "subject": claim.get("subject", ""),
                    "predicate": claim.get("predicate", ""),
                    "object": claim.get("object", ""),
                    "status": claim.get("status", "candidate"),
                    "source_type": claim.get("source_type", "provisional"),
                    "candidate_type": claim.get("candidate_type", ""),
                    "interpretation": claim.get("interpretation", ""),
                    "confidence": claim.get("confidence", 0.0),
                    "span_id": claim.get("span_id", ""),
                    "source_text": span.get("text", claim.get("object", "")),
                    "source_locator": span.get("locator", claim.get("span_id", "")),
                    "artifact": artifact.get("path", ""),
                    "artifact_sha256": artifact.get("sha256", ""),
                    "last_event": event,
                }
            )
        return tuple(records)


__all__ = ["RequirementsAnalysisDependencies", "RequirementsAnalysisService"]
