"""Deterministic, bounded multi-objective ranking and feedback."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.concept_design import (
    DisciplineEvaluation,
    LayoutCandidate,
    OptimizationRun,
)
from rflp_lite.domain.errors import ContractViolation


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    run: OptimizationRun
    candidates: tuple[LayoutCandidate, ...]
    evaluations: tuple[DisciplineEvaluation, ...]


def _objectives(objectives: Sequence[Mapping[str, object]]) -> tuple[tuple[str, str, str], ...]:
    result = []
    for item in objectives:
        discipline = str(item["discipline"])
        metric = str(item["metric"])
        direction = str(item["direction"])
        if direction not in {"maximize", "minimize"}:
            raise ContractViolation(f"unsupported objective direction: {direction}")
        result.append((discipline, metric, direction))
    return tuple(result)


def objective_vector(
    candidate_id: str,
    evaluations: Sequence[DisciplineEvaluation],
    objectives: Sequence[Mapping[str, object]],
) -> tuple[float, ...]:
    by_key = {
        (item.candidate_id, item.discipline, name.split(".")[-1]): float(value)
        for item in evaluations
        for name, value in item.metrics
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    vector = []
    for discipline, metric, _direction in _objectives(objectives):
        if (candidate_id, discipline, metric) not in by_key:
            raise ContractViolation(f"objective metric is missing: {discipline}.{metric}")
        vector.append(by_key[(candidate_id, discipline, metric)])
    return tuple(vector)


def _dominates(left: tuple[float, ...], right: tuple[float, ...], directions: Sequence[str]) -> bool:
    no_worse = True
    strictly_better = False
    for a, b, direction in zip(left, right, directions):
        if direction == "maximize":
            if a < b:
                no_worse = False
            if a > b:
                strictly_better = True
        else:
            if a > b:
                no_worse = False
            if a < b:
                strictly_better = True
    return no_worse and strictly_better


def pareto_front(
    vectors: Mapping[str, tuple[float, ...]],
    objectives: Sequence[tuple[str, str]] | Sequence[Mapping[str, object]],
) -> tuple[str, ...]:
    directions = tuple(
        item if isinstance(item, str)
        else item[0] if isinstance(item, tuple)
        else str(item["direction"])
        for item in objectives
    )
    ids = tuple(sorted(vectors))
    return tuple(
        candidate_id
        for candidate_id in ids
        if not any(
            other != candidate_id and _dominates(vectors[other], vectors[candidate_id], directions)
            for other in ids
        )
    )


def rank_evaluated_candidates(
    candidates: Sequence[LayoutCandidate],
    evaluations: Sequence[DisciplineEvaluation],
    objectives: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    by_candidate: dict[str, list[DisciplineEvaluation]] = {}
    for evaluation in evaluations:
        by_candidate.setdefault(evaluation.candidate_id, []).append(evaluation)
    definitions = _objectives(objectives)
    vectors: dict[str, tuple[float, ...]] = {}
    for candidate in candidates:
        candidate_evaluations = by_candidate.get(candidate.id, [])
        if not candidate_evaluations or any(item.status not in {"succeeded", "cached"} for item in candidate_evaluations):
            continue
        try:
            vectors[candidate.id] = objective_vector(candidate.id, candidate_evaluations, objectives)
        except ContractViolation:
            continue
    directions = tuple(item[2] for item in definitions)
    front = set(pareto_front(vectors, directions))
    ranked = []
    for candidate_id in sorted(vectors):
        dominated_by = sum(
            _dominates(vectors[other], vectors[candidate_id], directions)
            for other in vectors
            if other != candidate_id
        )
        ranked.append({
            "candidate_id": candidate_id,
            "objectives": vectors[candidate_id],
            "front": candidate_id in front,
            "rank": dominated_by,
        })
    return tuple(ranked)


def _call_generator(generate: Callable[..., object], pack: Mapping[str, object], front: tuple[LayoutCandidate, ...], seed: int) -> tuple[LayoutCandidate, ...]:
    try:
        value = generate(pack, front, seed)
    except TypeError:
        value = generate(seed, front)
    return tuple(value)


def run_optimization(
    pack: Mapping[str, object],
    evaluator_profile: Mapping[str, object],
    initial_candidates: Sequence[LayoutCandidate],
    initial_evaluations: Sequence[DisciplineEvaluation],
    generate: Callable[..., object],
    evaluate: Callable[..., object],
    iterations: int = 3,
    evaluation_budget: int = 30,
    base_seed: int = 42,
) -> OptimizationResult:
    if not 1 <= iterations <= 10:
        raise ContractViolation("iterations must be between 1 and 10")
    if not 3 <= evaluation_budget <= 500:
        raise ContractViolation("evaluation_budget must be between 3 and 500")
    candidates = list(initial_candidates)
    evaluations = list(initial_evaluations)
    objectives = pack.get("objectives", ())
    front_ids = tuple(item["candidate_id"] for item in rank_evaluated_candidates(candidates, evaluations, objectives) if item["front"])
    previous_hash = canonical_hash(front_ids)
    unchanged = 0
    stop_reason = "iteration_limit"
    iteration_records: list[tuple[str, object]] = [
        (
            "0",
            {
                "parent_ids": (),
                "candidate_ids": tuple(item.id for item in candidates),
                "front_ids": front_ids,
                "generation_index": 0,
            },
        )
    ]
    for iteration in range(iterations):
        if len(evaluations) >= evaluation_budget:
            stop_reason = "evaluation_budget"
            break
        front = tuple(item for item in candidates if item.id in front_ids)
        parent_ids = tuple(item.id for item in (front or tuple(candidates))[:3])
        generated = _call_generator(generate, pack, front or tuple(candidates), base_seed + iteration)
        remaining = max(0, evaluation_budget - len(evaluations))
        generated = generated[: max(1, remaining // max(1, len(pack.get("disciplines", ()))))]
        if not generated:
            stop_reason = "no_new_candidates"
            break
        batch = evaluate(generated, pack, evaluator_profile)
        batch_evaluations = tuple(getattr(batch, "evaluations", batch))
        candidates.extend(generated)
        evaluations.extend(batch_evaluations)
        ranked = rank_evaluated_candidates(candidates, evaluations, objectives)
        front_ids = tuple(item["candidate_id"] for item in ranked if item["front"])
        front_hash = canonical_hash(front_ids)
        unchanged = unchanged + 1 if front_hash == previous_hash else 0
        previous_hash = front_hash
        iteration_records.append(
            (
                str(iteration + 1),
                {
                    "parent_ids": parent_ids,
                    "candidate_ids": tuple(item.id for item in generated),
                    "front_ids": front_ids,
                    "generation_index": iteration + 1,
                },
            )
        )
        if unchanged >= 2:
            stop_reason = "front_unchanged"
            break
    formal_status = "passed" if evaluations and all(
        item.status in {"succeeded", "cached"} and item.evidence_status == "formal"
        for item in evaluations
    ) else "development"
    run_hash = canonical_hash({"front": front_ids, "iterations": iteration_records, "stop": stop_reason})
    run = OptimizationRun(
        id=f"OPT-{run_hash[:12]}", envelope_id=candidates[0].envelope_id if candidates else "",
        domain_pack_id=str(pack.get("id", "")), domain_pack_version=int(pack.get("version", 1)),
        candidate_ids=tuple(item.id for item in candidates), evaluation_ids=tuple(item.id for item in evaluations),
        iteration_records=tuple(iteration_records), front_candidate_ids=front_ids, seed=base_seed,
        stop_reason=stop_reason, input_hash=canonical_hash({"pack": pack, "seed": base_seed}),
        result_hash=run_hash, status="completed", evidence_status=formal_status,
    )
    return OptimizationResult(run, tuple(candidates), tuple(evaluations))


__all__ = ["OptimizationResult", "objective_vector", "pareto_front", "rank_evaluated_candidates", "run_optimization"]
