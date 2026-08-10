"""Executable acceptance evidence for concept functions 2.1 and 2.2."""

from __future__ import annotations

import json
from pathlib import Path
from collections.abc import Mapping

from rflp_lite.adapters.disciplines import discipline_registry
from rflp_lite.adapters.scheme_sources import read_scheme_rows
from rflp_lite.application.concept_design_service import run_concept_design
from rflp_lite.application.discipline_batch import evaluate_candidates, validate_evaluator_profile
from rflp_lite.application.domain_packs import load_domain_pack
from rflp_lite.application.scheme_library import import_scheme_rows
from rflp_lite.domain.canonical import canonical_hash


class _MemoryStore:
    def __init__(self):
        self.evaluations: dict[str, dict[str, object]] = {}
        self.runs: list[object] = []

    def load_discipline_evaluation(self, key: str):
        return self.evaluations.get(key)

    def save_discipline_evaluations(self, values):
        for value in values:
            if isinstance(value, Mapping):
                payload = dict(value)
                key = str(payload.get("cache_key", payload.get("id", "")))
            else:
                from rflp_lite.domain.canonical import to_primitive

                payload = to_primitive(value)
                key = str(payload["id"])
            self.evaluations[key] = payload

    def save_domain_pack(self, value):
        return value

    def save_indicator_envelopes(self, values):
        return None

    def save_layout_candidates(self, values):
        return None

    def save_optimization_runs(self, values):
        return None

    def save_concept_runs(self, values):
        self.runs.extend(values)

    def record_audit(self, kind, payload):
        return 1


def _load_profile(path: Path) -> dict[str, object]:
    try:
        return validate_evaluator_profile(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"evaluator profile is invalid: {path}") from exc


def run_concept_acceptance(
    pack_path: Path, schemes_path: Path, envelope_path: Path, evaluator_profile_path: Path
) -> dict[str, object]:
    pack = load_domain_pack(pack_path)
    rows = read_scheme_rows(schemes_path.name, schemes_path.read_bytes())
    imported = import_scheme_rows(pack, rows, str(schemes_path))
    profile = _load_profile(evaluator_profile_path)
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    registry = discipline_registry()
    first = run_concept_design(pack, profile, envelope, imported.records, registry, _MemoryStore())
    second = run_concept_design(pack, profile, envelope, imported.records, registry, _MemoryStore())
    candidate_hashes_first = tuple(item.result_hash for item in first.candidates)
    candidate_hashes_second = tuple(item.result_hash for item in second.candidates)
    evaluation_hashes_first = tuple(item.output_hash for item in first.evaluations)
    evaluation_hashes_second = tuple(item.output_hash for item in second.evaluations)

    class FailingStructures:
        id = "builtin.structures.v1"
        version = "1"
        source_kind = "analytical"

        def evaluate(self, candidate, profile):
            raise RuntimeError("simulated structures failure")

    failing_registry = dict(registry)
    failing_registry["builtin.structures.v1"] = FailingStructures()
    isolated = evaluate_candidates(
        (first.candidates[0],), pack, profile, failing_registry, _MemoryStore()
    )
    isolated_disciplines = {item.discipline: item.status for item in isolated.evaluations}
    checks = {
        "2.1.candidate_count": 3 <= len(first.candidates) <= 5,
        "2.1.hard_constraints": all(
            result.passed
            for candidate in first.candidates
            for result in candidate.constraints
            if result.severity == "hard"
        ),
        "2.1.reproducible": candidate_hashes_first == candidate_hashes_second
        and evaluation_hashes_first == evaluation_hashes_second,
        "2.2.three_disciplines": {item.discipline for item in first.evaluations}
        == {"aerodynamics", "structures", "weight_balance"},
        "2.2.failure_isolation": isolated_disciplines.get("structures") == "failed"
        and isolated_disciplines.get("aerodynamics") == "succeeded"
        and isolated_disciplines.get("weight_balance") == "succeeded",
        "2.2.optimization_trace": bool(first.optimization.front_candidate_ids)
        and bool(first.trace_links),
        "2.2.approval_gate": (
            first.formal_status == "passed"
            if profile.get("approvals")
            else first.formal_status == "development"
        ),
    }
    report = {
        "status": "passed" if all(checks.values()) else "failed",
        "formal_status": first.formal_status if first.formal_status == "passed" else "development_only",
        "checks": checks,
        "candidate_count": len(first.candidates),
        "candidate_hashes": candidate_hashes_first,
        "evaluation_hashes": evaluation_hashes_first,
        "run_hash": canonical_hash({"candidates": candidate_hashes_first, "evaluations": evaluation_hashes_first}),
        "rejected_scheme_rows": imported.rejected,
    }
    return report


__all__ = ["run_concept_acceptance"]
