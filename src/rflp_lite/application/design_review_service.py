"""Shared annotation and DFM/DFA review orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rflp_lite.application.detail_design_store import DetailDesignStore
from rflp_lite.domain.canonical import canonical_hash, to_primitive
from rflp_lite.domain.errors import ContractViolation, NotFoundError
from rflp_lite.ports.cad import DesignRulePort, DrawingPort


class DesignReviewService:
    """Generate shared 2D/3D annotations and reviewable manufacturing findings."""

    def __init__(
        self,
        repository,
        project_id: str,
        *,
        drawing: DrawingPort,
        rules: DesignRulePort,
    ) -> None:
        self.repository = repository
        self.project_id = project_id
        self.drawing = drawing
        self.rules = rules
        self.store = DetailDesignStore(repository, project_id)

    def annotate(self, model_id: str, model_payload: Mapping[str, Any]) -> dict[str, Any]:
        result = self.drawing.generate_annotations(model_payload)
        return {
            "model_id": model_id,
            "annotations": [to_primitive(item) for item in result.annotations],
            "diagnostics": list(result.diagnostics),
            "source_kind": "development",
        }

    def review(self, model_id: str, model_payload: Mapping[str, Any]) -> dict[str, Any]:
        input_hash = canonical_hash({"model_id": model_id, "model": model_payload})
        existing = next(
            (
                item for item in reversed(self.store.records("design_review"))
                if str(item.get("model_id", "")) == model_id and str(item.get("input_hash", "")) == input_hash
            ),
            None,
        )
        if existing is not None:
            return {**existing, "idempotent": True}
        annotations = self.drawing.generate_annotations(model_payload)
        findings = self.rules.review(
            model_payload,
            {"annotations": annotations.annotations},
        )
        open_critical = any(
            item.severity in {"critical", "high"} and item.status == "open"
            for item in findings.findings
        )
        review_id = f"design-review-{canonical_hash((self.project_id, model_id, input_hash))[:16]}"
        record = {
            "id": review_id,
            "model_id": model_id,
            "annotations": [to_primitive(item) for item in annotations.annotations],
            "findings": [to_primitive(item) for item in findings.findings],
            "status": "needs_review" if open_critical or any(item.status == "needs_review" for item in annotations.annotations) else "passed",
            "input_hash": input_hash,
            "diagnostics": list(annotations.diagnostics) + list(findings.diagnostics),
            "source_kind": "development",
            "rule_version": getattr(self.rules, "version", "unknown"),
        }
        self.store.save("design_review", record)
        self.store.record_audit(
            "cad.design_review_created",
            {"review_id": review_id, "model_id": model_id, "finding_count": len(findings.findings)},
        )
        return record

    def reviews(self) -> tuple[dict[str, Any], ...]:
        return self.store.records("design_review")

    def get_review(self, review_id: str) -> dict[str, Any]:
        record = self.store.latest("design_review", review_id)
        if record is None:
            raise NotFoundError(f"design review not found: {review_id}")
        return record

    def update_finding(self, review_id: str, finding_id: str, decision: str) -> dict[str, Any]:
        decision = decision.strip().casefold()
        status = {"confirm": "confirmed", "confirmed": "confirmed", "false_positive": "false_positive", "close": "closed", "closed": "closed"}.get(decision)
        if status is None:
            raise ContractViolation("decision must be confirm, false_positive or close")
        record = self.get_review(review_id)
        findings = [dict(item) for item in record.get("findings", ()) if isinstance(item, Mapping)]
        target = next((item for item in findings if str(item.get("id", "")) == finding_id), None)
        if target is None:
            raise NotFoundError(f"design finding not found: {finding_id}")
        target["status"] = status
        still_open = any(
            item.get("status") == "open" and item.get("severity") in {"critical", "high"}
            for item in findings
        )
        updated = {**record, "findings": findings, "status": "needs_review" if still_open else "passed"}
        self.store.save("design_review", updated)
        self.store.save(
            "finding_update",
            {"id": f"finding-update-{canonical_hash((review_id, finding_id, status))[:16]}", "review_id": review_id, "finding_id": finding_id, "decision": status},
        )
        self.store.record_audit(
            "cad.design_finding_updated",
            {"review_id": review_id, "finding_id": finding_id, "status": status},
        )
        return updated


__all__ = ["DesignReviewService"]
