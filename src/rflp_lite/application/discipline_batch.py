"""Bounded, cache-aware multidisciplinary evaluation orchestration."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from collections.abc import Mapping
from typing import Any

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.concept_design import DisciplineEvaluation, LayoutCandidate
from rflp_lite.domain.errors import ContractViolation


@dataclass(frozen=True, slots=True)
class EvaluationBatch:
    evaluations: tuple[DisciplineEvaluation, ...]
    candidate_status: dict[str, str]
    candidate_formal_status: dict[str, str]
    cache_hits: int


def _contract(message: str) -> ContractViolation:
    return ContractViolation(message)


def validate_evaluator_profile(payload: object) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise _contract("evaluator profile must be an object")
    if not isinstance(payload.get("id"), str) or not str(payload["id"]).strip():
        raise _contract("evaluator profile id is required")
    version = payload.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contract("evaluator profile version must be a positive integer")
    approvals = payload.get("approvals", {})
    if not isinstance(approvals, Mapping):
        raise _contract("evaluator profile approvals must be an object")
    normalized: dict[str, object] = {
        "id": str(payload["id"]),
        "version": version,
        "approvals": {},
    }
    for adapter_id, raw in approvals.items():
        if not isinstance(adapter_id, str) or not adapter_id.strip() or not isinstance(raw, Mapping):
            raise _contract("evaluator profile approval entry is invalid")
        adapter_version = raw.get("adapter_version")
        approved = raw.get("approved_for_formal", False)
        if not isinstance(adapter_version, str) or not adapter_version.strip() or not isinstance(approved, bool):
            raise _contract(f"approval for {adapter_id} is invalid")
        normalized["approvals"][adapter_id] = {
            "adapter_version": adapter_version,
            "approved_for_formal": approved,
            "basis": str(raw.get("basis", "")),
            "approved_by": str(raw.get("approved_by", "")),
            "approved_at": str(raw.get("approved_at", "")),
        }
    return normalized


def surrogate_is_valid(profile: Mapping[str, object], parameters: Mapping[str, object]) -> bool:
    validity = profile.get("validity_domain")
    if not isinstance(validity, Mapping):
        return False
    for name, raw_bound in validity.items():
        if not isinstance(raw_bound, Mapping) or "minimum" not in raw_bound or "maximum" not in raw_bound:
            return False
        value = parameters.get(str(name))
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        if float(value) < float(raw_bound["minimum"]) or float(value) > float(raw_bound["maximum"]):
            return False
    error = profile.get("validation_error", 0.0)
    maximum = profile.get("maximum_error", 0.0)
    return isinstance(error, (int, float)) and isinstance(maximum, (int, float)) and float(error) <= float(maximum)


def _payload_evaluation(payload: Mapping[str, object]) -> DisciplineEvaluation:
    def pairs(name: str) -> tuple[tuple[str, object], ...]:
        raw = payload.get(name, ())
        return tuple((str(item[0]), item[1]) for item in raw if isinstance(item, (list, tuple)) and len(item) == 2)

    return DisciplineEvaluation(
        id=str(payload["id"]),
        candidate_id=str(payload["candidate_id"]),
        discipline=str(payload.get("discipline", "")),
        adapter_id=str(payload["adapter_id"]),
        adapter_version=str(payload["adapter_version"]),
        source_kind=str(payload.get("source_kind", "analytical")),
        input_hash=str(payload["input_hash"]),
        output_hash=str(payload["output_hash"]),
        metrics=pairs("metrics"),
        status=str(payload["status"]),
        evidence_status=str(payload.get("evidence_status", "development")),
        validity=pairs("validity"),
        diagnostics=tuple(str(item) for item in payload.get("diagnostics", ())),
        log_ref=str(payload.get("log_ref", "")),
    )


def _load_cache(store: object, key: str) -> DisciplineEvaluation | None:
    loader = getattr(store, "load_discipline_evaluation", None)
    if loader is None:
        return None
    value = loader(key)
    if isinstance(value, DisciplineEvaluation):
        return value
    return _payload_evaluation(value) if isinstance(value, Mapping) else None


def _save_cache(store: object, key: str, value: DisciplineEvaluation) -> None:
    singular = getattr(store, "save_discipline_evaluation", None)
    if singular is not None:
        singular(key, value)
        return
    plural = getattr(store, "save_discipline_evaluations", None)
    if plural is not None:
        payload = {
            "id": value.id,
            "cache_key": key,
            "candidate_id": value.candidate_id,
            "discipline": value.discipline,
            "adapter_id": value.adapter_id,
            "adapter_version": value.adapter_version,
            "source_kind": value.source_kind,
            "input_hash": value.input_hash,
            "output_hash": value.output_hash,
            "metrics": value.metrics,
            "status": value.status,
            "evidence_status": value.evidence_status,
            "validity": value.validity,
            "diagnostics": value.diagnostics,
            "log_ref": value.log_ref,
        }
        plural((payload,))


def _defaults(pack: Mapping[str, object]) -> dict[str, object]:
    return {
        str(item["name"]): item["default"]
        for item in pack.get("parameters", ())
        if isinstance(item, Mapping) and "name" in item and "default" in item
    }


def _failed(candidate: LayoutCandidate, discipline: Mapping[str, object], adapter: object, status: str, error: str) -> DisciplineEvaluation:
    adapter_id = str(getattr(adapter, "id", discipline.get("adapter", "unknown")))
    adapter_version = str(getattr(adapter, "version", discipline.get("adapter_version", "unknown")))
    input_hash = canonical_hash({"candidate": candidate.result_hash, "discipline": discipline.get("id"), "adapter": adapter_id})
    output_hash = canonical_hash({"input": input_hash, "status": status, "error": error})
    return DisciplineEvaluation(
        id=f"{candidate.id}:{adapter_id}", candidate_id=candidate.id, discipline=str(discipline["id"]),
        adapter_id=adapter_id, adapter_version=adapter_version, source_kind=str(getattr(adapter, "source_kind", "unknown")),
        input_hash=input_hash, output_hash=output_hash, metrics=(), status=status,
        evidence_status="development", validity=(), diagnostics=(error,), log_ref="",
    )


def _approved(profile: Mapping[str, object], evaluation: DisciplineEvaluation) -> bool:
    approvals = profile.get("approvals", {})
    entry = approvals.get(evaluation.adapter_id) if isinstance(approvals, Mapping) else None
    return bool(
        isinstance(entry, Mapping)
        and entry.get("approved_for_formal") is True
        and entry.get("adapter_version") == evaluation.adapter_version
    )


def evaluate_candidates(
    candidates: tuple[LayoutCandidate, ...],
    pack: Mapping[str, object],
    evaluator_profile: Mapping[str, object],
    registry: Mapping[str, object],
    store: object,
    max_workers: int = 3,
) -> EvaluationBatch:
    if max_workers < 1:
        raise _contract("max_workers must be positive")
    profile = validate_evaluator_profile(evaluator_profile)
    disciplines = pack.get("disciplines", ())
    if not isinstance(disciplines, list) or not disciplines:
        raise _contract("domain pack disciplines must be a non-empty array")
    tasks: list[tuple[LayoutCandidate, Mapping[str, object]]] = [
        (candidate, discipline) for candidate in candidates for discipline in disciplines if isinstance(discipline, Mapping)
    ]
    results: dict[tuple[str, str], DisciplineEvaluation] = {}
    cache_hits = 0

    def run(task: tuple[LayoutCandidate, Mapping[str, object]]) -> tuple[tuple[str, str], DisciplineEvaluation, bool]:
        candidate, discipline = task
        adapter_id = str(discipline["adapter"])
        adapter = registry.get(adapter_id)
        if adapter is None:
            return (candidate.id, str(discipline["id"])), _failed(candidate, discipline, object(), "failed", f"adapter not registered: {adapter_id}"), False
        selected = adapter
        parameters = dict(candidate.parameters)
        if str(adapter_id).startswith("surrogate") and not surrogate_is_valid(discipline, parameters):
            fallback_id = discipline.get("fallback_adapter")
            if isinstance(fallback_id, str) and fallback_id in registry:
                selected = registry[fallback_id]
            else:
                return (candidate.id, str(discipline["id"])), _failed(candidate, discipline, adapter, "out_of_domain", "surrogate outside validity domain"), False
        key = canonical_hash({"candidate": candidate.result_hash, "discipline": discipline, "adapter": getattr(selected, "id", adapter_id), "adapter_version": getattr(selected, "version", ""), "evaluator_profile": (profile["id"], profile["version"])})
        cached = _load_cache(store, key)
        if cached is not None and cached.status == "succeeded":
            return (candidate.id, str(discipline["id"])), replace(cached, status="cached"), True
        adapter_profile = dict(discipline)
        adapter_profile["defaults"] = _defaults(pack)
        try:
            result = selected.evaluate(candidate, adapter_profile)
        except TimeoutError as exc:
            result = _failed(candidate, discipline, selected, "timeout", str(exc) or "adapter timed out")
        except Exception as exc:  # adapter boundary: isolate one task
            result = _failed(candidate, discipline, selected, "failed", f"{type(exc).__name__}: {exc}")
        result = replace(result, discipline=str(discipline["id"]), evidence_status="formal" if _approved(profile, result) else "development")
        if result.status == "succeeded":
            _save_cache(store, key, result)
        return (candidate.id, str(discipline["id"])), result, False

    with ThreadPoolExecutor(max_workers=min(max_workers, 8)) as executor:
        futures = [executor.submit(run, task) for task in tasks]
        for future in as_completed(futures):
            key, result, hit = future.result()
            results[key] = result
            cache_hits += int(hit)
    ordered = tuple(results[key] for key in sorted(results))
    candidate_status: dict[str, str] = {}
    candidate_formal_status: dict[str, str] = {}
    for candidate in candidates:
        values = tuple(results[(candidate.id, str(discipline["id"]))] for discipline in disciplines)
        complete = all(item.status in {"succeeded", "cached"} for item in values)
        candidate_status[candidate.id] = "complete" if complete else "partial"
        if not complete:
            candidate_formal_status[candidate.id] = "partial"
        elif all(_approved(profile, item) for item in values):
            candidate_formal_status[candidate.id] = "passed"
        else:
            candidate_formal_status[candidate.id] = "development"
    return EvaluationBatch(ordered, candidate_status, candidate_formal_status, cache_hits)


__all__ = ["EvaluationBatch", "evaluate_candidates", "surrogate_is_valid", "validate_evaluator_profile"]
