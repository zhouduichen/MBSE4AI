"""Project-scoped persistence bridge for concept-design records.

Concept records are immutable projections of a ModelGraph project.  They are
stored as audit payloads so M3/M4 does not introduce a second database or
another mutable source of engineering truth.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from rflp_lite.domain.canonical import to_primitive


class ConceptStore:
    """Adapt the v2 repository audit port to the concept services."""

    _KINDS = (
        "domain_pack",
        "indicator_envelope",
        "scheme_record",
        "layout_candidate",
        "discipline_evaluation",
        "optimization_run",
        "concept_run",
        "candidate_review",
    )

    def __init__(self, repository, project_id: str) -> None:
        self.repository = repository
        self.project_id = project_id

    def _event_kind(self, kind: str) -> str:
        return f"concept.record.{kind}"

    def _record(self, kind: str, value: object) -> dict[str, Any]:
        raw = dict(value) if isinstance(value, Mapping) else to_primitive(value)
        return {"record": raw}

    def _save(self, kind: str, values: Sequence[object]) -> None:
        for value in values:
            raw = dict(value) if isinstance(value, Mapping) else to_primitive(value)
            self.repository.record_audit(self.project_id, self._event_kind(kind), self._record(kind, raw))

    def _records(self, kind: str) -> tuple[dict[str, Any], ...]:
        events = self.repository.list_audit_events(self.project_id)
        selected = (
            event.get("payload", {}).get("record")
            for event in events
            if event.get("kind") == self._event_kind(kind)
            and isinstance(event.get("payload"), Mapping)
        )
        return tuple(dict(item) for item in selected if isinstance(item, Mapping))

    def save_domain_pack(self, value: Mapping[str, object]) -> None:
        self._save("domain_pack", (value,))

    def save_indicator_envelopes(self, values: Sequence[object]) -> None:
        self._save("indicator_envelope", values)

    def save_scheme_records(self, values: Sequence[object]) -> None:
        self._save("scheme_record", values)

    def save_layout_candidates(self, values: Sequence[object]) -> None:
        self._save("layout_candidate", values)

    def save_discipline_evaluations(self, values: Sequence[object]) -> None:
        self._save("discipline_evaluation", values)

    def save_optimization_runs(self, values: Sequence[object]) -> None:
        self._save("optimization_run", values)

    def save_concept_runs(self, values: Sequence[object]) -> None:
        self._save("concept_run", values)

    def save_candidate_reviews(self, values: Sequence[object]) -> None:
        self._save("candidate_review", values)

    def _latest(self, kind: str, record_id: str = "") -> dict[str, Any] | None:
        records = self._records(kind)
        matches = tuple(item for item in records if not record_id or str(item.get("id")) == record_id)
        return matches[-1] if matches else None

    def load_discipline_evaluation(self, cache_key: str) -> dict[str, Any] | None:
        for item in reversed(self._records("discipline_evaluation")):
            if str(item.get("cache_key", "")) == cache_key:
                return item
        return None

    def discipline_evaluations(self) -> tuple[dict[str, Any], ...]:
        return self._records("discipline_evaluation")

    def layout_candidates(self) -> tuple[dict[str, Any], ...]:
        return self._records("layout_candidate")

    def concept_runs(self) -> tuple[dict[str, Any], ...]:
        return self._records("concept_run")

    def load_concept_run(self, run_id: str) -> dict[str, Any] | None:
        return self._latest("concept_run", run_id)

    def record_audit(self, kind: str, payload: Mapping[str, object]) -> None:
        self.repository.record_audit(self.project_id, kind, payload)


__all__ = ["ConceptStore"]
