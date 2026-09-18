"""One application entry point for the complete engineering product flow."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from rflp_lite.domain.canonical import to_primitive
from rflp_lite.domain.errors import InputRequired


@dataclass(frozen=True, slots=True)
class ProductFlowResult:
    """A JSON-safe, revision-bound snapshot of one product-flow request."""

    status: str
    project_id: str
    generation: Mapping[str, object]
    concept: Mapping[str, object]
    cad: Mapping[str, object]
    deliverable: Mapping[str, object]
    revision: int
    snapshot_hash: str

    def as_dict(self) -> Mapping[str, object]:
        return {
            "status": self.status,
            "project_id": self.project_id,
            "generation": to_primitive(self.generation),
            "concept": to_primitive(self.concept),
            "cad": to_primitive(self.cad),
            "deliverable": to_primitive(self.deliverable),
            "revision": self.revision,
            "snapshot_hash": self.snapshot_hash,
        }


class EngineeringProductFlowService:
    """Compose the existing RFLP, concept, CAD and delivery services.

    This service deliberately stops at review boundaries.  Concept candidates
    are not applied and CAD plans are not approved or executed here.
    """

    def __init__(self, generation, concept, cad, deliverables) -> None:
        self.generation = generation
        self.concept = concept
        self.cad = cad
        self.deliverables = deliverables

    def run(
        self,
        project_id: str,
        *,
        requirement_text: str | None = None,
        document_ids: Sequence[str] = (),
        include_concept: bool = False,
        optimize_concept: bool = True,
        cad_intent_text: str | None = None,
        selected_structure_option_id: str = "",
        source_requirement_ids: Sequence[str] = (),
    ) -> ProductFlowResult:
        """Run the product chain and return its current human-review boundary."""

        generation_result = self.generation.generate(
            project_id,
            requirement_text=requirement_text,
            document_ids=tuple(str(item) for item in document_ids if str(item).strip()),
        )
        generation = _mapping(generation_result.as_dict())
        concept: Mapping[str, object] = {"status": "not_requested"}
        cad: Mapping[str, object] = {"status": "not_requested"}
        generation_status = str(generation.get("status", "failed"))
        if generation_status not in {"completed", "completed_with_warnings"}:
            deliverable = _mapping(self.deliverables.build(project_id))
            revision = int(deliverable.get("revision", generation.get("revision", 0)) or 0)
            snapshot_hash = str(deliverable.get("snapshot_hash", ""))
            return ProductFlowResult(
                generation_status,
                str(project_id),
                generation,
                concept,
                cad,
                deliverable,
                revision,
                snapshot_hash,
            )
        status = generation_status

        if include_concept:
            try:
                concept_result = self.concept.run_from_requirements(optimize=optimize_concept)
            except InputRequired as exc:
                concept = {
                    "status": "needs_input",
                    "input": to_primitive(exc.details),
                }
                status = "needs_input"
            else:
                concept = {
                    "status": "completed",
                    "run": to_primitive(concept_result),
                }

        if status in {"completed", "completed_with_warnings"} and cad_intent_text and str(cad_intent_text).strip():
            draft = self.cad.create_intent(
                str(cad_intent_text).strip(),
                source_requirement_ids=tuple(
                    str(item) for item in source_requirement_ids if str(item).strip()
                ),
            )
            draft_payload = to_primitive(draft)
            if draft.status != "ready":
                cad = {
                    "status": "needs_clarification",
                    "draft": draft_payload,
                }
                status = "needs_clarification"
            else:
                plan = self.cad.create_plan(
                    draft.draft_id,
                    selected_structure_option_id=str(selected_structure_option_id).strip(),
                )
                cad = {
                    "status": "needs_approval" if plan.get("status") == "ready" else "needs_clarification",
                    "draft": draft_payload,
                    "plan": to_primitive(plan),
                }
                status = str(cad["status"])

        deliverable = _mapping(self.deliverables.build(project_id))
        revision = int(deliverable.get("revision", generation.get("revision", 0)) or 0)
        snapshot_hash = str(deliverable.get("snapshot_hash", ""))
        return ProductFlowResult(
            status,
            str(project_id),
            generation,
            _mapping(concept),
            _mapping(cad),
            deliverable,
            revision,
            snapshot_hash,
        )


def _mapping(value: Any) -> Mapping[str, object]:
    raw = to_primitive(value)
    return dict(raw) if isinstance(raw, Mapping) else {}


__all__ = ["EngineeringProductFlowService", "ProductFlowResult"]
