"""Shared text/document preparation for all product analysis entry points."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

from rflp_lite.application.requirement_input import RequirementInputService
from rflp_lite.application.requirements_use_case import RequirementsUseCaseService
from rflp_lite.domain.errors import InputRequired
from rflp_lite.repository.port import ModelRepository


@dataclass(frozen=True, slots=True)
class InputPreparationResult:
    """Evidence that one analysis entry point prepared its input boundary."""

    project_id: str
    mode: str
    status: str
    prepared: bool
    revision: int
    draft_id: str = ""
    input_hash: str = ""
    created_entity_count: int = 0
    created_relation_count: int = 0
    diagnostics: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "mode": self.mode,
            "status": self.status,
            "prepared": self.prepared,
            "revision": self.revision,
            "draft_id": self.draft_id,
            "input_hash": self.input_hash,
            "created_entity_count": self.created_entity_count,
            "created_relation_count": self.created_relation_count,
            "diagnostics": list(self.diagnostics),
        }


class InputPreparationService:
    """Prepare text/documents once before either generation workflow runs.

    The configured OpenAI-compatible adapter opts into the structured intake
    contract. Injected stage-only runtimes retain the legacy requirement input
    adapter so existing stage contracts do not receive an unsupported lens.
    """

    def __init__(
        self,
        repository: ModelRepository,
        runtime,
        *,
        runtime_selection=None,
        audit_kind: str = "input_preparation.completed",
        output_budget: int | None = None,
    ) -> None:
        self.repository = repository
        self.runtime = runtime
        self.runtime_selection = runtime_selection
        self.audit_kind = str(audit_kind).strip() or "input_preparation.completed"
        self.output_budget = max(
            512,
            int(
                output_budget
                or getattr(runtime_selection, "max_output_tokens", None)
                or 4096
            ),
        )

    def prepare(
        self,
        project_id: str,
        *,
        requirement_text: str | None = None,
        document_ids: Sequence[str] = (),
    ) -> InputPreparationResult:
        clean_project_id = str(project_id).strip()
        if not clean_project_id:
            raise InputRequired("project id is required")
        explicit_text = str(requirement_text or "").strip()
        selected_document_ids = tuple(
            dict.fromkeys(
                str(item).strip()
                for item in document_ids
                if str(item).strip()
            )
        )
        graph = self.repository.load_graph(clean_project_id)
        has_input = bool(
            explicit_text
            or selected_document_ids
            or self.repository.has_documents(clean_project_id)
        )
        if not has_input:
            if graph.has_active_entities:
                return InputPreparationResult(
                    clean_project_id,
                    "existing_graph",
                    "skipped",
                    False,
                    graph.revision,
                )
            raise InputRequired("requirement_text or an existing requirement is required")

        model = getattr(self.runtime, "model", None)
        if model is not None and not getattr(model, "supports_requirements_intake", False):
            RequirementInputService(self.repository, clean_project_id).ensure(
                text=explicit_text or None,
                document_ids=selected_document_ids,
            )
            revision = self.repository.load_graph(clean_project_id).revision
            return InputPreparationResult(
                clean_project_id,
                "legacy_requirement_input",
                "completed",
                True,
                revision,
            )

        intake = RequirementsUseCaseService(
            self.repository,
            clean_project_id,
            model=model,
            profile_id=str(getattr(self.runtime_selection, "profile_id", "offline-rule")),
            provider_id=str(getattr(self.runtime_selection, "provider_id", "offline")),
            model_id=str(getattr(self.runtime_selection, "model_id", "rule-runtime")),
            max_output_tokens=self.output_budget,
        )
        draft = intake.create_draft(
            text=explicit_text or None,
            document_ids=selected_document_ids,
        )
        applied = intake.apply_draft(draft)
        result = InputPreparationResult(
            clean_project_id,
            "structured_intake",
            draft.status,
            True,
            int(applied.get("revision", graph.revision) or graph.revision),
            draft.draft_id,
            draft.input_hash,
            int(applied.get("created_entity_count", 0) or 0),
            int(applied.get("created_relation_count", 0) or 0),
            tuple(draft.diagnostics),
        )
        self.repository.record_audit(
            clean_project_id,
            self.audit_kind,
            {
                "draft_id": result.draft_id,
                "status": result.status,
                "input_hash": result.input_hash,
                "mode": result.mode,
                "revision": result.revision,
                "created_entity_count": result.created_entity_count,
                "created_relation_count": result.created_relation_count,
                "profile_id": str(getattr(self.runtime_selection, "profile_id", "offline-rule")),
                "provider_id": str(getattr(self.runtime_selection, "provider_id", "offline")),
                "model_id": str(getattr(self.runtime_selection, "model_id", "rule-runtime")),
                "diagnostics": list(result.diagnostics),
            },
        )
        return result


__all__ = ["InputPreparationResult", "InputPreparationService"]
