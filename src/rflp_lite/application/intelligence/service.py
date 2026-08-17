"""Composition root for the reviewable discovery pipeline."""

from __future__ import annotations

import json

from rflp_lite.application.intelligence.bridge import bridge_discovery_to_workbench
from rflp_lite.application.intelligence.coverage import evaluate_coverage, fill_high_priority_gaps
from rflp_lite.application.intelligence.expansion import expand_candidates
from rflp_lite.application.intelligence.intake import attach_seed_model
from rflp_lite.application.intelligence.normalization import normalize_candidate_sets
from rflp_lite.application.intelligence.review import edit_candidate, review_candidate
from rflp_lite.domain.canonical import canonical_json
from rflp_lite.domain.errors import AdapterFailure
from rflp_lite.ports.generative_model import GenerativeModel


class IntelligenceService:
    def __init__(self, pack: dict[str, object], model: GenerativeModel | None) -> None:
        self.pack = pack
        self.model = model

    def draft(self, state: dict[str, object], *, lens_ids: tuple[str, ...] | None = None) -> dict[str, object]:
        result = attach_seed_model(state, self.pack)
        if self.model is None:
            result = json.loads(canonical_json(result))
            result["discovery"].setdefault("diagnostics", []).append({"code": "generative_model_unavailable", "severity": "warning", "message": "大模型未配置，已保留领域包覆盖检查。"})
            return evaluate_coverage(result, self.pack)
        try:
            result = expand_candidates(result, self.pack, self.model, lens_ids)
            result = normalize_candidate_sets(result)
            result = evaluate_coverage(result, self.pack)
            if lens_ids is None:
                return fill_high_priority_gaps(result, self.pack, self.model)
            return result
        except AdapterFailure as exc:
            degraded = json.loads(canonical_json(result))
            degraded["discovery"].setdefault("diagnostics", []).append({"code": "generative_model_failed", "severity": "warning", "message": str(exc)})
            return evaluate_coverage(degraded, self.pack)

    def review(self, state: dict[str, object], candidate_id: str, decision: str, expected_revision: int) -> dict[str, object]:
        return review_candidate(state, candidate_id, decision, expected_revision)

    def edit(self, state: dict[str, object], candidate_id: str, payload: dict[str, object], expected_revision: int) -> dict[str, object]:
        return edit_candidate(state, candidate_id, payload, expected_revision, self.pack)

    def finalize(self, state: dict[str, object]) -> dict[str, object]:
        return bridge_discovery_to_workbench(evaluate_coverage(state, self.pack))
