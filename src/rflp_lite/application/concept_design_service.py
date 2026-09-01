"""End-to-end application service for concept layout and MDO runs.

This module is intentionally small and dependency-free.  It composes the
validated declaration-only domain pack with the fixed core records and the
replaceable discipline registry.  Persistence is duck-typed so the service
works with :class:`SQLiteRepository` as well as the tiny in-memory stores used
by tests and integrations.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
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
from rflp_lite.domain.canonical import canonical_hash, canonical_json, to_primitive
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
    layout_manifests: tuple[dict[str, object], ...] = ()


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


def _candidate_values(candidate: LayoutCandidate) -> dict[str, object]:
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
        iteration_records=(("0", {"candidate_ids": tuple(item.id for item in candidates), "front_ids": front}),),
        front_candidate_ids=front,
        seed=seed,
        stop_reason="evaluation_budget",
        input_hash=input_hash,
        result_hash=result_hash,
        status="completed",
        evidence_status=("passed" if evaluations and all(item.evidence_status == "formal" for item in evaluations) else "development"),
    )
    return OptimizationResult(run, candidates, evaluations)


def run_concept_design(
    pack: Mapping[str, object],
    evaluator_profile: Mapping[str, object],
    envelope_payload: Mapping[str, object],
    schemes: Iterable[SchemeRecord | Mapping[str, object]],
    registry: Mapping[str, object],
    store: object,
    optimize: bool = True,
) -> ConceptRunResult:
    """Run the complete deterministic concept-layout workflow.

    The service owns no global state.  Calling it again with changed inputs
    creates a new immutable run ID and leaves earlier records untouched.
    """

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
    initial_candidates = generate_layout_candidates(
        normalized_pack, envelope, scheme_values, matches, seed=seed
    )
    if not initial_candidates:
        raise ContractViolation("concept design could not generate feasible candidates")

    initial_hash = canonical_hash(
        {
            "pack": normalized_pack,
            "evaluator_profile": evaluator_profile,
            "envelope": envelope,
            "schemes": scheme_values,
            "registry": _registry_identity(registry),
            "optimize": bool(optimize),
        }
    )
    _call(store, "save_domain_pack", normalized_pack)
    _save_one(store, "save_indicator_envelopes", envelope)
    _call(store, "save_layout_candidates", initial_candidates)

    batch = evaluate_candidates(
        tuple(initial_candidates), normalized_pack, evaluator_profile, registry, store
    )
    initial_evaluations = tuple(batch.evaluations)

    if optimize:
        # Keep the customer-facing concept result at the required 3–5
        # candidates.  Task 8's bounded optimizer still computes the Pareto
        # front; this budget prevents an opaque second batch from changing the
        # initial design set during the first workflow run.
        def generate(_pack: Mapping[str, object], _front: object, next_seed: int) -> tuple[LayoutCandidate, ...]:
            return generate_layout_candidates(
                normalized_pack, envelope, scheme_values, matches, seed=next_seed
            )

        def evaluate(
            generated: Iterable[LayoutCandidate],
            current_pack: Mapping[str, object],
            profile: Mapping[str, object],
        ) -> object:
            return evaluate_candidates(tuple(generated), current_pack, profile, registry, store)

        optimized = run_optimization(
            normalized_pack,
            evaluator_profile,
            tuple(initial_candidates),
            initial_evaluations,
            generate,
            evaluate,
            iterations=3,
            evaluation_budget=max(3, len(initial_evaluations)),
            base_seed=seed,
        )
    else:
        optimized = _initial_optimization(
            normalized_pack, envelope, tuple(initial_candidates), initial_evaluations, seed
        )

    candidates = tuple(initial_candidates)
    evaluations = tuple(initial_evaluations)
    optimization = optimized.run
    layout_manifests = tuple(
        build_layout_manifest(normalized_pack, candidate, candidates)
        for candidate in candidates
    )
    formal_status = (
        "passed"
        if evaluations and all(item.evidence_status == "formal" for item in evaluations)
        else "development"
    )
    trace_links = _trace_links(envelope, matches, candidates, evaluations, optimization)
    result_hash = canonical_hash(
        {
            "input_hash": initial_hash,
            "matches": matches,
            "candidates": candidates,
            "evaluations": evaluations,
            "optimization": optimization,
            "trace_links": trace_links,
            "layout_manifests": layout_manifests,
        }
    )
    result = ConceptRunResult(
        id=f"{normalized_pack.get('id_prefix', 'CONCEPT')}-RUN-{result_hash[:12]}",
        envelope=envelope,
        matches=tuple(matches),
        candidates=candidates,
        evaluations=evaluations,
        optimization=optimization,
        trace_links=trace_links,
        status="completed",
        formal_status=formal_status,
        input_hash=initial_hash,
        result_hash=result_hash,
        layout_manifests=layout_manifests,
    )
    _call(store, "save_discipline_evaluations", evaluations)
    _call(store, "save_optimization_runs", (optimization,))
    _call(store, "save_concept_runs", (result,))
    _call(
        store,
        "record_audit",
        "concept.run_completed",
        {
            "id": result.id,
            "result_hash": result.result_hash,
            "candidate_count": len(result.candidates),
            "evaluation_count": len(result.evaluations),
            "formal_status": result.formal_status,
        },
    )
    return result


def review_layout_candidate(
    candidate_id: str,
    decision: str,
    store: object,
    *,
    run_id: str = "",
) -> dict[str, object]:
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
    )


__all__ = [
    "ConceptRunResult",
    "concept_run_from_payload",
    "review_layout_candidate",
    "run_concept_design",
]
