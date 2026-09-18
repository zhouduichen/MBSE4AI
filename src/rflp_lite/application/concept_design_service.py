"""End-to-end application service for concept layout and MDO runs.

This module is intentionally small and dependency-free.  It composes the
validated declaration-only domain pack with the fixed core records and the
replaceable discipline registry.  Persistence is duck-typed so the service
works with :class:`SQLiteRepository` as well as the tiny in-memory stores used
by tests and integrations.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any
from rflp_lite.application.domain_packs import validate_domain_pack
from rflp_lite.application.discipline_batch import evaluate_candidates
from rflp_lite.application.layout_generation import generate_layout_candidates
from rflp_lite.application.layout_evidence import build_layout_manifest
from rflp_lite.application.multidisciplinary_optimization import (
    OptimizationResult,
    rank_evaluated_candidates,
    run_optimization,
)
from rflp_lite.application.parameter_rules import create_indicator_envelope
from rflp_lite.application.scheme_retrieval import find_similar_schemes
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.concept_design import (
    DisciplineEvaluation,
    IndicatorEnvelope,
    LayoutCandidate,
    OptimizationRun,
    SchemeRecord,
    SimilarityMatch,
)
from rflp_lite.domain.errors import ContractViolation


@dataclass(frozen=True, slots=True)
class ConceptRunResult:
    id: str
    envelope: IndicatorEnvelope
    matches: tuple[SimilarityMatch, ...]
    candidates: tuple[LayoutCandidate, ...]
    evaluations: tuple[DisciplineEvaluation, ...]
    optimization: OptimizationRun
    trace_links: tuple[tuple[str, str, str], ...]
    status: str
    formal_status: str
    input_hash: str
    result_hash: str
    layout_manifests: tuple[dict[str, Any], ...] = ()
    evaluation_summary: Mapping[str, object] = field(default_factory=dict)


def _call(store: object, name: str, *args: object) -> object | None:
    function = getattr(store, name, None)
    return function(*args) if callable(function) else None


def _save_one(store: object, plural: str, value: object) -> None:
    function = getattr(store, plural, None)
    if callable(function):
        function((value,))


def _registry_identity(registry: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (
                str(identifier),
                str(getattr(adapter, "version", "")),
            )
            for identifier, adapter in registry.items()
        )
    )


def _candidate_values(candidate: LayoutCandidate) -> dict[str, Any]:
    return dict(candidate.parameters)


def _as_similarity(value: object) -> SimilarityMatch:
    if isinstance(value, SimilarityMatch):
        return value
    if not isinstance(value, Mapping):
        raise ContractViolation("stored similarity match is invalid")
    differences = tuple(
        (str(item[0]), float(item[1]))
        for item in value.get("feature_differences", ())
        if isinstance(item, (tuple, list)) and len(item) == 2
    )
    return SimilarityMatch(
        scheme_id=str(value.get("scheme_id", "")),
        similarity=float(value.get("similarity", 0.0)),
        feature_differences=differences,
        missing_features=tuple(str(item) for item in value.get("missing_features", ())),
    )


def _as_scheme(value: object) -> SchemeRecord | Mapping[str, object]:
    """Accept either a live SchemeRecord or its canonical JSON payload."""

    if isinstance(value, SchemeRecord):
        return value
    if not isinstance(value, Mapping):
        raise ContractViolation("scheme record is invalid")
    # Retrieval/generation need tuple parameters when reading a record back
    # from SQLite (canonical JSON represents tuples as arrays).
    pairs = lambda name: tuple(
        (str(item[0]), item[1])
        for item in value.get(name, ())
        if isinstance(item, (tuple, list)) and len(item) == 2
    )
    return SchemeRecord(
        id=str(value["id"]), object_type=str(value["object_type"]),
        schema_version=int(value["schema_version"]), domain_pack_id=str(value["domain_pack_id"]),
        domain_pack_version=int(value["domain_pack_version"]), revision=int(value["revision"]),
        status=str(value["status"]), source=str(value["source"]),
        parameters=pairs("parameters"), extensions=pairs("extensions"),
        content_hash=str(value["content_hash"]),
    )
def _as_candidate(value: object) -> LayoutCandidate:
    if isinstance(value, LayoutCandidate):
        return value
    if not isinstance(value, Mapping):
        raise ContractViolation("stored layout candidate is invalid")
    constraints = tuple(
        item
        for item in value.get("constraints", ())
        if isinstance(item, Mapping)
    )
    from rflp_lite.domain.concept_design import ConstraintResult

    normalized_constraints = tuple(ConstraintResult(**dict(item)) for item in constraints)
    return LayoutCandidate(
        id=str(value["id"]),
        envelope_id=str(value["envelope_id"]),
        domain_pack_id=str(value["domain_pack_id"]),
        domain_pack_version=int(value["domain_pack_version"]),
        reference_ids=tuple(str(item) for item in value.get("reference_ids", ())),
        similarity_matches=tuple(_as_similarity(item) for item in value.get("similarity_matches", ())),
        parameters=tuple((str(item[0]), item[1]) for item in value.get("parameters", ()) if isinstance(item, (tuple, list)) and len(item) == 2),
        parameter_sources=tuple((str(item[0]), str(item[1])) for item in value.get("parameter_sources", ()) if isinstance(item, (tuple, list)) and len(item) == 2),
        geometry=tuple((str(item[0]), item[1]) for item in value.get("geometry", ()) if isinstance(item, (tuple, list)) and len(item) == 2),
        svg=str(value.get("svg", "")),
        constraints=normalized_constraints,
        feasible=bool(value.get("feasible", False)),
        infeasible_reasons=tuple(str(item) for item in value.get("infeasible_reasons", ())),
        status=str(value.get("status", "")),
        generator_version=str(value.get("generator_version", "")),
        seed=int(value.get("seed", 0)),
        input_hash=str(value.get("input_hash", "")),
        result_hash=str(value.get("result_hash", "")),
    )


def _as_evaluation(value: object) -> DisciplineEvaluation:
    if isinstance(value, DisciplineEvaluation):
        return value
    if not isinstance(value, Mapping):
        raise ContractViolation("stored discipline evaluation is invalid")
    pairs = lambda name: tuple(
        (str(item[0]), item[1])
        for item in value.get(name, ())
        if isinstance(item, (tuple, list)) and len(item) == 2
    )
    return DisciplineEvaluation(
        id=str(value["id"]),
        candidate_id=str(value["candidate_id"]),
        discipline=str(value.get("discipline", "")),
        adapter_id=str(value["adapter_id"]),
        adapter_version=str(value["adapter_version"]),
        source_kind=str(value.get("source_kind", "")),
        input_hash=str(value["input_hash"]),
        output_hash=str(value["output_hash"]),
        metrics=pairs("metrics"),
        status=str(value["status"]),
        evidence_status=str(value.get("evidence_status", "development")),
        validity=pairs("validity"),
        diagnostics=tuple(str(item) for item in value.get("diagnostics", ())),
        log_ref=str(value.get("log_ref", "")),
        implementation_hash=str(value.get("implementation_hash", "")),
        approval_profile_hash=str(value.get("approval_profile_hash", "")),
        approval_diagnostics=tuple(str(item) for item in value.get("approval_diagnostics", ())),
    )


def _trace_links(
    envelope: IndicatorEnvelope,
    matches: tuple[SimilarityMatch, ...],
    candidates: tuple[LayoutCandidate, ...],
    evaluations: tuple[DisciplineEvaluation, ...],
    optimization: OptimizationRun,
) -> tuple[tuple[str, str, str], ...]:
    links: list[tuple[str, str, str]] = []
    for requirement_id in envelope.source_requirement_ids:
        links.append((requirement_id, "refines", envelope.id))
    for match in matches:
        for candidate in candidates:
            if match.scheme_id in candidate.reference_ids:
                links.append((match.scheme_id, "influences", candidate.id))
    for evaluation in evaluations:
        links.append((evaluation.candidate_id, "evaluatedBy", evaluation.id))
        links.append((evaluation.id, "contributesTo", optimization.id))
    for candidate_id in optimization.front_candidate_ids:
        links.append((optimization.id, "ranks", candidate_id))
    return tuple(dict.fromkeys(links))


def _initial_optimization(
    pack: Mapping[str, object],
    envelope: IndicatorEnvelope,
    candidates: tuple[LayoutCandidate, ...],
    evaluations: tuple[DisciplineEvaluation, ...],
    seed: int,
) -> OptimizationResult:
    ranked = rank_evaluated_candidates(candidates, evaluations, pack.get("objectives", ()))
    front = tuple(str(item["candidate_id"]) for item in ranked if item.get("front"))
    input_hash = canonical_hash({"pack": pack, "envelope": envelope, "seed": seed})
    result_hash = canonical_hash({"front": front, "candidate_ids": tuple(item.id for item in candidates), "evaluation_ids": tuple(item.id for item in evaluations)})
    run = OptimizationRun(
        id=f"{pack.get('id_prefix', 'OPT')}-OPT-{result_hash[:12]}",
        envelope_id=envelope.id,
        domain_pack_id=str(pack.get("id", "")),
        domain_pack_version=int(pack.get("version", 1)),
        candidate_ids=tuple(item.id for item in candidates),
        evaluation_ids=tuple(item.id for item in evaluations),
        iteration_records=(
            (
                "0",
                {
                    "parent_ids": (),
                    "candidate_ids": tuple(item.id for item in candidates),
                    "front_ids": front,
                    "generation_index": 0,
                },
            ),
        ),
        front_candidate_ids=front,
        seed=seed,
        stop_reason="evaluation_budget",
        input_hash=input_hash,
        result_hash=result_hash,
        status="completed",
        evidence_status=("passed" if evaluations and all(item.evidence_status == "formal" for item in evaluations) else "development"),
    )
    return OptimizationResult(run, candidates, evaluations)


def _parent_inputs(
    pack: Mapping[str, object], parents: tuple[LayoutCandidate, ...]
) -> tuple[tuple[SchemeRecord, ...], tuple[SimilarityMatch, ...]]:
    """Expose selected candidates as deterministic generation references."""

    schemes = tuple(
        SchemeRecord(
            id=parent.id,
            object_type=str(pack.get("object_type", "layout")),
            schema_version=int(pack.get("schema_version", 1)),
            domain_pack_id=str(pack.get("id", "")),
            domain_pack_version=int(pack.get("version", 1)),
            revision=1,
            status="generated-parent",
            source=f"parent:{parent.id}",
            parameters=parent.parameters,
            extensions=(),
            content_hash=parent.result_hash,
        )
        for parent in parents[:3]
    )
    matches = tuple(
        SimilarityMatch(
            scheme_id=parent.id,
            similarity=1.0,
            feature_differences=(),
            missing_features=(),
        )
        for parent in schemes
    )
    return schemes, matches


def _prepare_run(pack, envelope_payload, schemes):
    normalized_pack = validate_domain_pack(pack)
    if not isinstance(envelope_payload, Mapping):
        raise ContractViolation("envelope payload must be an object")
    scheme_values = tuple(_as_scheme(item) for item in schemes)
    envelope = create_indicator_envelope(
        normalized_pack,
        envelope_payload,
        tuple(str(item) for item in envelope_payload.get("source_requirement_ids", ())),
    )
    retrieval = normalized_pack.get("retrieval", {})
    limit = int(retrieval.get("limit", 5)) if isinstance(retrieval, Mapping) else 5
    matches = find_similar_schemes(normalized_pack, envelope, scheme_values, limit=limit)
    seed = int(normalized_pack.get("generation", {}).get("seed", 42))
    candidates = generate_layout_candidates(normalized_pack, envelope, scheme_values, matches, seed=seed)
    if not candidates:
        raise ContractViolation("concept design could not generate feasible candidates")
    return normalized_pack, envelope, scheme_values, matches, seed, tuple(candidates)


def _initial_hash(pack, profile, envelope, schemes, registry, optimize):
    return canonical_hash({
        "pack": pack,
        "evaluator_profile": profile,
        "envelope": envelope,
        "schemes": schemes,
        "registry": _registry_identity(registry),
        "optimize": bool(optimize),
    })


def _optimized_run(pack, profile, envelope, initial, evaluations, registry, store, optimize, seed):
    if not optimize:
        return _initial_optimization(pack, envelope, initial, evaluations, seed)

    def generate(_pack, front, next_seed):
        parents = tuple(item for item in front if isinstance(item, LayoutCandidate))
        parent_schemes, parent_matches = _parent_inputs(pack, parents or initial)
        return generate_layout_candidates(pack, envelope, parent_schemes, parent_matches, seed=next_seed + 1000)

    def evaluate(generated, current_pack, current_profile):
        return evaluate_candidates(tuple(generated), current_pack, current_profile, registry, store)

    budget = max(3, len(evaluations) + 3 * len(pack.get("disciplines", ())))
    return run_optimization(pack, profile, initial, evaluations, generate, evaluate, iterations=3, evaluation_budget=budget, base_seed=seed)


def _evaluation_summary(
    pack: Mapping[str, object],
    candidates: tuple[LayoutCandidate, ...],
    evaluations: tuple[DisciplineEvaluation, ...],
    optimization: OptimizationRun,
) -> dict[str, object]:
    discipline_ids = tuple(
        str(item["id"])
        for item in pack.get("disciplines", ())
        if isinstance(item, Mapping) and item.get("id")
    )
    by_candidate: dict[str, list[DisciplineEvaluation]] = {}
    for evaluation in evaluations:
        by_candidate.setdefault(evaluation.candidate_id, []).append(evaluation)
    candidate_rows: list[dict[str, object]] = []
    complete_count = 0
    formal_count = 0
    for candidate in candidates:
        rows = by_candidate.get(candidate.id, [])
        by_discipline = {item.discipline: item for item in rows}
        missing = [name for name in discipline_ids if name not in by_discipline]
        failed = [
            item.discipline
            for item in rows
            if item.status not in {"succeeded", "cached"}
        ]
        complete = not missing and not failed
        formal = complete and all(
            by_discipline[name].evidence_status == "formal"
            for name in discipline_ids
            if name in by_discipline
        )
        complete_count += int(complete)
        formal_count += int(formal)
        candidate_rows.append(
            {
                "candidate_id": candidate.id,
                "status": "complete" if complete else "partial",
                "formal_status": "passed" if formal else "development",
                "missing_disciplines": missing,
                "failed_disciplines": failed,
                "evaluation_ids": [item.id for item in rows],
                "front": candidate.id in optimization.front_candidate_ids,
            }
        )
    return {
        "schema_version": "concept-evaluation-summary.v1",
        "candidate_count": len(candidates),
        "evaluation_count": len(evaluations),
        "complete_candidate_count": complete_count,
        "formal_candidate_count": formal_count,
        "failed_evaluation_count": sum(
            item.status not in {"succeeded", "cached"} for item in evaluations
        ),
        "cached_evaluation_count": sum(item.status == "cached" for item in evaluations),
        "front_candidate_ids": list(optimization.front_candidate_ids),
        "stop_reason": optimization.stop_reason,
        "optimization_evidence_status": optimization.evidence_status,
        "iterations": [
            {"index": index, "record": record}
            for index, record in optimization.iteration_records
        ],
        "candidates": candidate_rows,
    }


def _build_result(pack, envelope, matches, optimized, initial_hash):
    candidates = tuple(optimized.candidates)
    evaluations = tuple(optimized.evaluations)
    optimization = optimized.run
    manifests = tuple(build_layout_manifest(pack, candidate, candidates) for candidate in candidates)
    formal = bool(evaluations) and all(
        item.status in {"succeeded", "cached"} and item.evidence_status == "formal"
        for item in evaluations
    ) and optimization.evidence_status == "passed"
    trace_links = _trace_links(envelope, matches, candidates, evaluations, optimization)
    evaluation_summary = _evaluation_summary(pack, candidates, evaluations, optimization)
    result_hash = canonical_hash({"input_hash": initial_hash, "matches": matches, "candidates": candidates, "evaluations": evaluations, "optimization": optimization, "trace_links": trace_links, "layout_manifests": manifests, "evaluation_summary": evaluation_summary})
    return ConceptRunResult(
        id=f"{pack.get('id_prefix', 'CONCEPT')}-RUN-{result_hash[:12]}",
        envelope=envelope, matches=tuple(matches), candidates=candidates, evaluations=evaluations,
        optimization=optimization, trace_links=trace_links, status="completed",
        formal_status="passed" if formal else "development", input_hash=initial_hash,
        result_hash=result_hash, layout_manifests=manifests,
        evaluation_summary=evaluation_summary,
    )


def _persist_result(store, result):
    _call(store, "save_layout_candidates", result.candidates)
    _call(store, "save_discipline_evaluations", result.evaluations)
    _call(store, "save_optimization_runs", (result.optimization,))
    _call(store, "save_concept_runs", (result,))
    _call(store, "record_audit", "concept.run_completed", {
        "id": result.id, "result_hash": result.result_hash,
        "candidate_count": len(result.candidates),
        "evaluation_count": len(result.evaluations),
        "formal_status": result.formal_status,
    })


def run_concept_design(pack, evaluator_profile, envelope_payload, schemes, registry, store, optimize=True):
    """Run the complete deterministic concept-layout workflow."""
    normalized, envelope, scheme_values, matches, seed, initial = _prepare_run(pack, envelope_payload, schemes)
    initial_hash = _initial_hash(normalized, evaluator_profile, envelope, scheme_values, registry, optimize)
    _call(store, "save_domain_pack", normalized)
    _save_one(store, "save_indicator_envelopes", envelope)
    _call(store, "save_layout_candidates", initial)
    batch = evaluate_candidates(initial, normalized, evaluator_profile, registry, store)
    optimized = _optimized_run(normalized, evaluator_profile, envelope, initial, tuple(batch.evaluations), registry, store, optimize, seed)
    result = _build_result(normalized, envelope, matches, optimized, initial_hash)
    _persist_result(store, result)
    return result


def review_layout_candidate(
    candidate_id: str,
    decision: str,
    store: object,
    *,
    run_id: str = "",
) -> dict[str, Any]:
    """Persist a human decision for a complete, feasible candidate.

    Reviews are append-only records keyed by candidate ID.  A candidate that
    has not completed every declared discipline evaluation cannot be accepted
    or rejected because it is not yet reviewable.
    """

    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise ContractViolation("candidate_id is required")
    if decision not in {"accepted", "rejected"}:
        raise ContractViolation("candidate review decision must be accepted or rejected")
    raw_candidates = _call(store, "layout_candidates") or ()
    candidate = next(
        (_as_candidate(item) for item in raw_candidates if _as_candidate(item).id == candidate_id),
        None,
    )
    if candidate is None:
        raise ContractViolation(f"layout candidate not found: {candidate_id}")
    raw_evaluations = _call(store, "discipline_evaluations") or ()
    evaluations = tuple(
        _as_evaluation(item)
        for item in raw_evaluations
        if _as_evaluation(item).candidate_id == candidate_id
    )
    if not candidate.feasible or not evaluations or any(
        item.status not in {"succeeded", "cached"} for item in evaluations
    ):
        raise ContractViolation("only a complete feasible candidate can be reviewed")
    if decision == "accepted" and any(item.evidence_status != "formal" for item in evaluations):
        raise ContractViolation("only formally approved evaluations can be accepted")
    review_hash = canonical_hash(
        {"candidate_id": candidate_id, "decision": decision, "run_id": run_id, "candidate_hash": candidate.result_hash}
    )
    review = {
        "id": f"REVIEW-{review_hash[:16]}",
        "candidate_id": candidate_id,
        "run_id": run_id,
        "decision": decision,
        "candidate_result_hash": candidate.result_hash,
        "input_hash": canonical_hash({"candidate_id": candidate_id, "candidate_result_hash": candidate.result_hash}),
        "result_hash": review_hash,
        "status": "recorded",
    }
    _call(store, "save_candidate_reviews", (review,))
    _call(store, "record_audit", "concept.candidate_reviewed", review)
    return review


def concept_run_from_payload(value: Mapping[str, object]) -> ConceptRunResult:
    """Rehydrate a persisted concept run for read-only facade calls."""

    if not isinstance(value, Mapping):
        raise ContractViolation("concept run payload is invalid")
    envelope_raw = value.get("envelope")
    if not isinstance(envelope_raw, Mapping):
        raise ContractViolation("concept run envelope is invalid")
    envelope = IndicatorEnvelope(
        id=str(envelope_raw["id"]), object_type=str(envelope_raw["object_type"]),
        schema_version=int(envelope_raw["schema_version"]), domain_pack_id=str(envelope_raw["domain_pack_id"]),
        domain_pack_version=int(envelope_raw["domain_pack_version"]), revision=int(envelope_raw["revision"]),
        status=str(envelope_raw["status"]), source_requirement_ids=tuple(str(i) for i in envelope_raw.get("source_requirement_ids", ())),
        parameters=tuple((str(i[0]), i[1]) for i in envelope_raw.get("parameters", ()) if isinstance(i, (tuple, list)) and len(i) == 2),
        bounds=tuple((str(i[0]), float(i[1]), float(i[2])) for i in envelope_raw.get("bounds", ()) if isinstance(i, (tuple, list)) and len(i) == 3),
        input_hash=str(envelope_raw["input_hash"]),
    )
    optimization_raw = value.get("optimization")
    if not isinstance(optimization_raw, Mapping):
        raise ContractViolation("concept run optimization is invalid")
    optimization = OptimizationRun(
        id=str(optimization_raw["id"]), envelope_id=str(optimization_raw["envelope_id"]),
        domain_pack_id=str(optimization_raw["domain_pack_id"]), domain_pack_version=int(optimization_raw["domain_pack_version"]),
        candidate_ids=tuple(str(i) for i in optimization_raw.get("candidate_ids", ())), evaluation_ids=tuple(str(i) for i in optimization_raw.get("evaluation_ids", ())),
        iteration_records=tuple((str(i[0]), i[1]) for i in optimization_raw.get("iteration_records", ()) if isinstance(i, (tuple, list)) and len(i) == 2),
        front_candidate_ids=tuple(str(i) for i in optimization_raw.get("front_candidate_ids", ())), seed=int(optimization_raw["seed"]),
        stop_reason=str(optimization_raw["stop_reason"]), input_hash=str(optimization_raw["input_hash"]), result_hash=str(optimization_raw["result_hash"]),
        status=str(optimization_raw["status"]), evidence_status=str(optimization_raw.get("evidence_status", "development")),
    )
    return ConceptRunResult(
        id=str(value["id"]), envelope=envelope,
        matches=tuple(_as_similarity(item) for item in value.get("matches", ())),
        candidates=tuple(_as_candidate(item) for item in value.get("candidates", ())),
        evaluations=tuple(_as_evaluation(item) for item in value.get("evaluations", ())),
        optimization=optimization,
        trace_links=tuple(tuple(str(i) for i in link) for link in value.get("trace_links", ())),
        status=str(value.get("status", "")), formal_status=str(value.get("formal_status", "development")),
        input_hash=str(value["input_hash"]), result_hash=str(value["result_hash"]),
        layout_manifests=tuple(
            dict(item) for item in value.get("layout_manifests", ()) if isinstance(item, Mapping)
        ),
        evaluation_summary=(
            dict(value.get("evaluation_summary", {}))
            if isinstance(value.get("evaluation_summary", {}), Mapping)
            else {}
        ),
    )


__all__ = [
    "ConceptRunResult",
    "concept_run_from_payload",
    "review_layout_candidate",
    "run_concept_design",
]
