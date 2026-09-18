"""Orchestration for intent-to-CAD execution and ModelGraph integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rflp_lite.application.detail_design_store import DetailDesignStore
from rflp_lite.application.design_intent import DesignIntentDraft, DesignIntentService
from rflp_lite.application.requirement_scope import root_requirement_ids
from rflp_lite.domain.canonical import canonical_hash, to_primitive
from rflp_lite.domain.detail_design import (
    CadExecutionPlan,
    CadOperation,
    ClarificationQuestion,
    DesignIntent,
)
from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.errors import ContractViolation, NotFoundError
from rflp_lite.domain.model import AddEntity, Patch, Relate, UpdateEntity
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.ports.cad import CadOperationResult, CadPort


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _intent_from_payload(payload: Mapping[str, Any]) -> DesignIntent:
    raw = _mapping(payload.get("intent")) or payload
    raw_parameters = raw.get("parameters", ())
    if isinstance(raw_parameters, Mapping):
        parameters = tuple((str(key), value) for key, value in raw_parameters.items())
    else:
        parameters = tuple(
            (str(item.get("name")), item.get("value"))
            for item in raw_parameters
            if isinstance(item, Mapping) and item.get("name")
        )
    return DesignIntent(
        id=str(raw.get("id", payload.get("draft_id", "intent-unknown"))),
        statement=str(raw.get("statement", "")),
        target_kind=str(raw.get("target_kind", "part")),
        target_name=str(raw.get("target_name", "待确认零件")),
        parameters=parameters,
        material=str(raw.get("material", "")),
        connection_requirements=tuple(str(item) for item in raw.get("connection_requirements", raw.get("connections", ()))),
        context_model_ids=tuple(str(item) for item in raw.get("context_model_ids", ())),
        source_requirement_ids=tuple(str(item) for item in raw.get("source_requirement_ids", ())),
        confidence=float(raw.get("confidence", 0.0)),
        provenance=str(raw.get("provenance", "rule")),
    )


def _clarifications(payload: Mapping[str, Any]) -> tuple[ClarificationQuestion, ...]:
    raw = payload.get("clarifications", ())
    return tuple(
        ClarificationQuestion(
            id=str(item.get("id", f"clarification-{canonical_hash(item)[:12]}")),
            question=str(item.get("question", "")),
            ambiguity=str(item.get("ambiguity", "")),
            options=tuple(str(option) for option in item.get("options", ())),
            recommendation=str(item.get("recommendation", "")),
            rationale=str(item.get("rationale", "")),
            severity=str(item.get("severity", "high")),
            status=str(item.get("status", "open")),
        )
        for item in raw
        if isinstance(item, Mapping)
    )


def _draft_from_payload(payload: Mapping[str, Any]) -> DesignIntentDraft:
    intent = _intent_from_payload(payload)
    return DesignIntentDraft(
        draft_id=str(payload.get("draft_id", "")),
        project_id=str(payload.get("project_id", "")),
        input_hash=str(payload.get("input_hash", "")),
        status=str(payload.get("status", "needs_clarification")),
        payload=dict(payload),
        intent=intent,
        clarifications=_clarifications(payload),
        provider_id=str(payload.get("provider_id", "")),
        model_id=str(payload.get("model_id", "")),
        diagnostics=tuple(str(item) for item in payload.get("diagnostics", ())),
        created_at=float(payload.get("created_at", 0.0)),
    )


def _plan_from_payload(payload: Mapping[str, Any]) -> CadExecutionPlan:
    operations = tuple(
        CadOperation(
            id=str(item.get("id", "")),
            operation=str(item.get("operation", "")),
            parameters=tuple((str(key), value) for key, value in _mapping(item.get("parameters")).items()),
            depends_on=tuple(str(value) for value in item.get("depends_on", ())),
            expected_result=str(item.get("expected_result", "")),
            reversible=bool(item.get("reversible", True)),
        )
        for item in payload.get("operations", ())
        if isinstance(item, Mapping)
    )
    return CadExecutionPlan(
        id=str(payload.get("id", "")),
        intent_id=str(payload.get("intent_id", "")),
        operations=operations,
        risks=tuple(str(item) for item in payload.get("risks", ())),
        status=str(payload.get("status", "draft")),
        approval_status=str(payload.get("approval_status", "pending")),
        preview_hash=str(payload.get("preview_hash", "")),
        model_context_ids=tuple(str(item) for item in payload.get("model_context_ids", ())),
        source_requirement_ids=tuple(str(item) for item in payload.get("source_requirement_ids", ())),
    )


def _number(parameters: Mapping[str, Any], name: str) -> float | None:
    value = parameters.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if float(value) > 0 else None


def _plan_operations(intent: DesignIntent) -> tuple[CadOperation, ...]:
    values = dict(intent.parameters)
    operations: list[CadOperation] = [
        CadOperation(
            "create-part",
            "create_part",
            (("part_id", intent.id),),
            (),
            "创建参数化零件文档",
        )
    ]
    length = _number(values, "length_mm")
    width = _number(values, "width_mm")
    height = _number(values, "height_mm")
    if length and width and height:
        operations.append(
            CadOperation(
                "create-box",
                "create_box",
                (
                    ("part_id", intent.id),
                    ("length_mm", length),
                    ("width_mm", width),
                    ("height_mm", height),
                ),
                ("create-part",),
                "创建基础包络实体",
            )
        )
    diameter = _number(values, "diameter_mm")
    if diameter and "孔" in intent.statement:
        operations.append(
            CadOperation(
                "add-hole",
                "add_hole",
                (
                    ("part_id", intent.id),
                    ("diameter_mm", diameter),
                    ("depth_mm", height or diameter * 2),
                    ("x_mm", (length or diameter) / 2),
                    ("y_mm", (width or diameter) / 2),
                ),
                ("create-box",),
                "创建孔特征",
            )
        )
    if intent.material:
        operations.append(
            CadOperation(
                "set-material",
                "set_material",
                (("part_id", intent.id), ("material", intent.material)),
                (operations[-1].id,),
                "写入材料属性",
            )
        )
    return tuple(operations)


class CadWorkflowService:
    """Review-gated design-intent, CAD-preview and graph-application workflow."""

    def __init__(
        self,
        repository,
        project_id: str,
        *,
        cad: CadPort,
        intent_service: DesignIntentService,
    ) -> None:
        self.repository = repository
        self.project_id = project_id
        self.cad = cad
        self.intent_service = intent_service
        self.store = DetailDesignStore(repository, project_id)

    def capabilities(self) -> dict[str, Any]:
        return self.cad.capabilities().as_dict()

    def create_intent(
        self,
        text: str,
        *,
        source_requirement_ids: tuple[str, ...] = (),
    ) -> DesignIntentDraft:
        effective_source_ids = source_requirement_ids or root_requirement_ids(
            self.repository.load_graph(self.project_id)
        )
        draft = self.intent_service.create_draft(
            self.project_id,
            text,
            source_requirement_ids=effective_source_ids,
        )
        self.store.save("design_intent_draft", draft.as_dict())
        return draft

    def drafts(self) -> tuple[DesignIntentDraft, ...]:
        return tuple(_draft_from_payload(item) for item in self.store.records("design_intent_draft"))

    def get_draft(self, draft_id: str) -> DesignIntentDraft:
        raw = self.store.latest("design_intent_draft", draft_id)
        if raw is None:
            raise NotFoundError(f"design intent draft not found: {draft_id}")
        return _draft_from_payload(raw)

    def create_plan(self, draft_id: str) -> dict[str, Any]:
        draft = self.get_draft(draft_id)
        operations = _plan_operations(draft.intent)
        plan_id = f"cad-plan-{canonical_hash((self.project_id, draft.intent.id, operations))[:16]}"
        status = "needs_clarification" if any(item.severity == "high" for item in draft.clarifications) else "ready"
        plan = CadExecutionPlan(
            id=plan_id,
            intent_id=draft.intent.id,
            operations=operations,
            risks=tuple(item.ambiguity for item in draft.clarifications),
            status=status,
            approval_status="pending",
            source_requirement_ids=draft.intent.source_requirement_ids,
        )
        preview: CadOperationResult | None = None
        diagnostics: tuple[str, ...] = ()
        try:
            preview = self.cad.preview_plan(plan)
        except ContractViolation as exc:
            diagnostics = (str(exc),)
        if preview is not None:
            plan = CadExecutionPlan(
                id=plan.id,
                intent_id=plan.intent_id,
                operations=plan.operations,
                risks=plan.risks,
                status=plan.status,
                approval_status=plan.approval_status,
                preview_hash=preview.model.artifact_hash,
                model_context_ids=plan.model_context_ids,
                source_requirement_ids=plan.source_requirement_ids,
            )
        record = {
            **plan.as_dict(),
            "draft_id": draft.draft_id,
            "intent": draft.intent.as_dict(),
            "preview": to_primitive(preview.model_payload) if preview else None,
            "diagnostics": list(diagnostics) + list(preview.diagnostics if preview else ()),
            "capabilities": self.capabilities(),
        }
        self.store.save("cad_execution_plan", record)
        return record

    def plans(self) -> tuple[dict[str, Any], ...]:
        return self.store.records("cad_execution_plan")

    def get_plan(self, plan_id: str) -> dict[str, Any]:
        record = self.store.latest("cad_execution_plan", plan_id)
        if record is None:
            raise NotFoundError(f"CAD plan not found: {plan_id}")
        return record

    def approve_plan(self, plan_id: str) -> dict[str, Any]:
        record = self.get_plan(plan_id)
        draft = self.get_draft(str(record.get("draft_id", "")))
        if any(item.severity == "high" and item.status == "open" for item in draft.clarifications):
            raise ContractViolation("CAD plan cannot be approved while high-severity clarifications are open")
        plan = _plan_from_payload(record)
        approved = CadExecutionPlan(
            id=plan.id,
            intent_id=plan.intent_id,
            operations=plan.operations,
            risks=plan.risks,
            status="approved",
            approval_status="approved",
            preview_hash=plan.preview_hash,
            model_context_ids=plan.model_context_ids,
            source_requirement_ids=plan.source_requirement_ids,
        )
        updated = {**record, **approved.as_dict(), "approval_event": "approved"}
        self.store.save("cad_execution_plan", updated)
        self.store.record_audit("cad.plan_approved", {"plan_id": plan_id, "plan_hash": approved.plan_hash})
        return updated

    def execute_plan(self, plan_id: str) -> dict[str, Any]:
        record = self.get_plan(plan_id)
        plan = _plan_from_payload(record)
        if plan.approval_status != "approved":
            raise ContractViolation("CAD plan must be approved before execution")
        existing = next((item for item in reversed(self.store.records("cad_model")) if item.get("plan_id") == plan_id), None)
        if existing is not None and str(existing.get("plan_hash", "")) == plan.plan_hash:
            return {**existing, "idempotent": True}
        result = self.cad.execute_plan(plan)
        output = {
            "id": result.model.id,
            "plan_id": plan.id,
            "plan_hash": plan.plan_hash,
            "intent_id": plan.intent_id,
            "model": result.model.as_dict(),
            "model_payload": to_primitive(result.model_payload),
            "diagnostics": list(result.diagnostics),
            "capabilities": self.capabilities(),
        }
        self.store.save("cad_model", output)
        self.store.record_audit("cad.model_executed", {"model_id": result.model.id, "plan_id": plan.id})
        return output

    def models(self) -> tuple[dict[str, Any], ...]:
        return self.store.records("cad_model")

    def get_model(self, model_id: str) -> dict[str, Any]:
        record = self.store.latest("cad_model", model_id)
        if record is None:
            raise NotFoundError(f"CAD model not found: {model_id}")
        return record

    def apply_model(self, model_id: str) -> dict[str, Any]:
        model_record = self.get_model(model_id)
        graph = self.repository.load_graph(self.project_id)
        intent = self.get_draft_for_intent(str(model_record.get("intent_id", ""))).intent
        reference = _mapping(model_record.get("model"))
        review = next(
            (
                item for item in reversed(self.store.records("design_review"))
                if str(item.get("model_id", "")) == model_id
            ),
            None,
        )
        design_payload = {
            "representation_kind": "cad_model",
            "design_intent": intent.as_dict(),
            "cad_model_reference": dict(reference),
            "cad_model_payload": model_record.get("model_payload", {}),
            "source_requirement_ids": list(intent.source_requirement_ids),
        }
        if review is not None:
            design_payload["design_review"] = dict(review)
        entity = make_entity(
            EntityKind.PHYSICAL_BLOCK,
            intent.target_name,
            design_payload,
            status=EntityStatus.ACCEPTED,
            producer=Producer.LLM if intent.provenance == "llm" else Producer.RULE,
            confidence=intent.confidence,
            source_ids=(intent.id, model_id),
            revision=graph.revision,
        )
        existing = graph.entity_index.get(entity.id)
        if existing is not None:
            current_review = existing.payload.get("design_review")
            if review is None or isinstance(current_review, Mapping) and current_review.get("id") == review.get("id"):
                return {"model": model_record, "entity": existing.as_dict(), "idempotent": True, "revision": graph.revision}
            patch = Patch.create(
                self.project_id,
                "cad.apply_model",
                (UpdateEntity(existing.id, {"payload": {"design_review": dict(review)}}),),
                f"回接 CAD 模型审查 {model_id}",
                graph.revision,
            )
            revision = self.repository.append_patch(self.project_id, patch, graph.revision)
            updated = self.repository.load_graph(self.project_id).entity_index[existing.id]
            self.store.record_audit(
                "cad.model_review_attached",
                {"model_id": model_id, "entity_id": existing.id, "review_id": review.get("id"), "revision": revision.sequence},
            )
            return {"model": model_record, "entity": updated.as_dict(), "revision": to_primitive(revision)}
        operations: list[Any] = [AddEntity(entity)]
        operations.extend(
            Relate(requirement_id, RelationPredicate.SATISFIED_BY, entity.id)
            for requirement_id in intent.source_requirement_ids
            if requirement_id in graph.entity_index
        )
        patch = Patch.create(
            self.project_id,
            "cad.apply_model",
            tuple(operations),
            f"应用 CAD 模型 {model_id}",
            graph.revision,
        )
        revision = self.repository.append_patch(self.project_id, patch, graph.revision)
        self.store.record_audit(
            "cad.model_applied",
            {"model_id": model_id, "entity_id": entity.id, "revision": revision.sequence},
        )
        return {"model": model_record, "entity": entity.as_dict(), "revision": to_primitive(revision)}

    def get_draft_for_intent(self, intent_id: str) -> DesignIntentDraft:
        for draft in reversed(self.drafts()):
            if draft.intent.id == intent_id:
                return draft
        raise NotFoundError(f"design intent not found: {intent_id}")


__all__ = ["CadWorkflowService"]
