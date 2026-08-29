"""Use cases for incremental, coverage, and full requirements reanalysis."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rflp_lite.application.intelligence.enrichment_jobs import EnrichmentJobRunner
from rflp_lite.application.intelligence.identity import ensure_workbench_metadata
from rflp_lite.application.use_cases.dependencies import ReanalyzeRequirementsDeps
from rflp_lite.application.workspaces import WorkspaceRef
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import ContractViolation


@dataclass(frozen=True, slots=True)
class ReanalyzeRequirementsCommand:
    workspace: WorkspaceRef
    mode: str
    delta_region_ids: tuple[str, ...] = ()


# Backwards-compatible public name used by early callers of this module.
ReanalyzeRequirementsDependencies = ReanalyzeRequirementsDeps


class ReanalyzeRequirementsUseCase:
    def __init__(self, dependencies: Any):
        self.dependencies = dependencies

    def execute(
        self, command: ReanalyzeRequirementsCommand, model: Any = None
    ) -> dict[str, object]:
        if command.mode not in {"incremental", "coverage_audit", "full_reanalysis"}:
            raise ContractViolation("未知需求分析模式")
        state = self.dependencies.load_state(command.workspace)
        if not isinstance(state, dict):
            raise ContractViolation("requirements workbench is empty")
        state = ensure_workbench_metadata(state)
        scope = state.get("project_scope")
        scope = scope if isinstance(scope, dict) else {}
        revision = int(state.get("revision", 0) or 0)
        content_revision = int(
            state.get("content_revision", revision) or 0
        )
        input_hash = str(scope.get("input_hash", ""))
        config_hash = canonical_hash(
            {
                "analysis_config": state.get("analysis_config", {}),
                "provider_id": str(getattr(model, "provider_id", "")),
                "model_id": str(getattr(model, "model_id", "")),
            }
        )
        runner = self.dependencies.runner_factory(command.workspace.path)
        return runner.submit(
            model,
            input_hash=input_hash,
            mode=command.mode,
            snapshot_revision=revision,
            snapshot_content_revision=content_revision,
            analysis_config_hash=config_hash,
            delta_region_ids=tuple(command.delta_region_ids),
            idempotency_key=(
                f"{command.workspace.name}:{content_revision}:"
                f"{command.mode}:{config_hash}"
            ),
        )


__all__ = [
    "ReanalyzeRequirementsCommand",
    "ReanalyzeRequirementsDependencies",
    "ReanalyzeRequirementsUseCase",
]
