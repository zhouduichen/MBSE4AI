"""Audit-backed persistence for detail-design workflow records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from rflp_lite.domain.canonical import to_primitive


class DetailDesignStore:
    """Keep design-intent and CAD workflow projections in the project audit log."""

    _KINDS = (
        "design_intent_draft",
        "cad_execution_plan",
        "cad_model",
        "design_annotation",
        "design_review",
        "finding_update",
    )

    def __init__(self, repository, project_id: str) -> None:
        self.repository = repository
        self.project_id = project_id

    def _event_kind(self, kind: str) -> str:
        if kind not in self._KINDS:
            raise ValueError(f"unsupported detail-design record kind: {kind}")
        return f"detail_design.record.{kind}"

    def save(self, kind: str, value: Mapping[str, Any] | object) -> dict[str, Any]:
        raw = dict(value) if isinstance(value, Mapping) else to_primitive(value)
        record = dict(raw) if isinstance(raw, Mapping) else {"value": raw}
        self.repository.record_audit(
            self.project_id,
            self._event_kind(kind),
            {"record": record},
        )
        return record

    def records(self, kind: str) -> tuple[dict[str, Any], ...]:
        event_kind = self._event_kind(kind)
        records: list[dict[str, Any]] = []
        for event in self.repository.list_audit_events(self.project_id):
            if event.get("kind") != event_kind:
                continue
            payload = event.get("payload")
            if not isinstance(payload, Mapping) or not isinstance(payload.get("record"), Mapping):
                continue
            records.append(dict(payload["record"]))
        return tuple(records)

    def latest(self, kind: str, record_id: str = "") -> dict[str, Any] | None:
        values = self.records(kind)
        matches = tuple(
            item for item in values
            if not record_id or str(item.get("id", item.get("draft_id", ""))) == record_id
        )
        return matches[-1] if matches else None

    def save_many(self, kind: str, values: Sequence[Mapping[str, Any] | object]) -> None:
        for value in values:
            self.save(kind, value)

    def record_audit(self, kind: str, payload: Mapping[str, Any]) -> None:
        self.repository.record_audit(self.project_id, kind, payload)


__all__ = ["DetailDesignStore"]
