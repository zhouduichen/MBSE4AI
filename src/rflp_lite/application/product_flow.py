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

    By default this service stops at review boundaries.  An explicit
    ``complete_design`` request can carry the selected downstream records
    through the existing apply/approve/execute services and still returns the
    review evidence and warnings.
    """

    def __init__(self, generation, concept, cad, design_review, deliverables) -> None:
        self.generation = generation
        self.concept = concept
        self.cad = cad
        self.design_review = design_review
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
        complete_design: bool = False,
        selected_concept_candidate_id: str = "",
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
                if complete_design:
                    selected_candidate_id = _select_concept_candidate(
                        concept_result,
                        selected_concept_candidate_id,
                    )
                    applied = self.concept.apply_candidate(
                        selected_candidate_id,
                        concept_result.id,
                    )
                    concept = {
                        **concept,
                        "selected_candidate_id": selected_candidate_id,
                        "apply": to_primitive(applied),
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
                if complete_design and plan.get("status") == "ready":
                    cad, status = _complete_cad_design(
                        self.cad,
                        self.design_review,
                        draft_payload,
                        plan,
                    )
                else:
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


def _select_concept_candidate(result, requested_id: str) -> str:
    candidates = tuple(result.candidates)
    if not candidates:
        raise InputRequired("concept design produced no candidate layout")
    requested = str(requested_id).strip()
    if requested:
        if not any(item.id == requested for item in candidates):
            raise InputRequired(
                f"selected concept candidate is not in the current run: {requested}"
            )
        return requested
    front_ids = tuple(
        str(item)
        for item in result.evaluation_summary.get("front_candidate_ids", ())
    )
    return next((item.id for item in candidates if item.id in front_ids), candidates[0].id)


def _complete_cad_design(cad, design_review, draft_payload, plan):
    approved = cad.approve_plan(str(plan["id"]))
    model = cad.execute_plan(str(plan["id"]))
    review = design_review.review(str(model["id"]), model["model_payload"])
    applied = cad.apply_model(str(model["id"]))
    warning = str(review.get("status", "needs_review")) != "passed"
    return (
        {
            "status": "completed_with_warnings" if warning else "completed",
            "draft": draft_payload,
            "plan": to_primitive(approved),
            "model": to_primitive(model),
            "review": to_primitive(review),
            "apply": to_primitive(applied),
        },
        "completed_with_warnings" if warning else "completed",
    )


__all__ = ["EngineeringProductFlowService", "ProductFlowResult"]
