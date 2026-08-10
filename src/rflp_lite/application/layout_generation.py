"""Deterministic reference-guided concept-layout candidate generation."""

from __future__ import annotations

import math
import random
from collections.abc import Iterable, Mapping
from dataclasses import replace

from rflp_lite.application.layout_render import render_layout_svg
from rflp_lite.application.parameter_rules import derive_parameters, evaluate_constraints, normalize_parameters
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.concept_design import (
    ConstraintResult,
    IndicatorEnvelope,
    LayoutCandidate,
    SchemeRecord,
    SimilarityMatch,
)
from rflp_lite.domain.errors import ContractViolation


GENERATOR_VERSION = "layout-generator-v1"


def _contract(message: str) -> ContractViolation:
    return ContractViolation(message)


def _parameter_specs(pack: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    raw = pack.get("parameters")
    if not isinstance(raw, list):
        raise _contract("domain pack parameters must be an array")
    specs: dict[str, Mapping[str, object]] = {}
    for item in raw:
        if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
            raise _contract("domain pack parameter declaration is invalid")
        specs[str(item["name"])] = item
    return specs


def _parameter_values(value: object, label: str) -> dict[str, object]:
    if isinstance(value, IndicatorEnvelope):
        return dict(value.parameters)
    if isinstance(value, SchemeRecord):
        return dict(value.parameters)
    if isinstance(value, LayoutCandidate):
        return dict(value.parameters)
    if isinstance(value, Mapping):
        raw = value.get("parameters", value)
        if not isinstance(raw, Mapping):
            raise _contract(f"{label} parameters must be an object")
        return dict(raw)
    raise _contract(f"{label} must be an envelope, scheme, or object")


def _scheme_id(value: object) -> str:
    if isinstance(value, (SchemeRecord, SimilarityMatch)):
        return value.id if isinstance(value, SchemeRecord) else value.scheme_id
    if isinstance(value, Mapping):
        identifier = value.get("id", value.get("scheme_id"))
        if isinstance(identifier, str) and identifier.strip():
            return identifier
    raise _contract("scheme or match id must be a non-empty string")


def _match_id(value: object) -> str:
    if isinstance(value, SimilarityMatch):
        return value.scheme_id
    if isinstance(value, Mapping):
        identifier = value.get("scheme_id", value.get("id"))
        if isinstance(identifier, str) and identifier.strip():
            return identifier
    raise _contract("similarity match must contain scheme_id")


def _match_similarity(value: object) -> float:
    if isinstance(value, SimilarityMatch):
        return float(value.similarity)
    if isinstance(value, Mapping):
        raw = value.get("similarity", 0.0)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise _contract("similarity must be numeric")
        return float(raw)
    return 0.0


def _match_value(value: object, scheme_id: str) -> SimilarityMatch:
    if isinstance(value, SimilarityMatch):
        return value
    if isinstance(value, Mapping):
        raw_differences = value.get("feature_differences", ())
        raw_missing = value.get("missing_features", ())
        differences = tuple(
            (str(item[0]), float(item[1]))
            for item in raw_differences
            if isinstance(item, (tuple, list)) and len(item) == 2
        )
        return SimilarityMatch(
            scheme_id=scheme_id,
            similarity=_match_similarity(value),
            feature_differences=differences,
            missing_features=tuple(str(item) for item in raw_missing),
        )
    return SimilarityMatch(scheme_id, 0.0, (), ())


def _generation(pack: Mapping[str, object]) -> tuple[int, int, int, float, int, str]:
    raw = pack.get("generation", {})
    if not isinstance(raw, Mapping):
        raise _contract("domain pack generation must be an object")
    minimum = raw.get("candidate_count_min", 3)
    maximum = raw.get("candidate_count_max", 5)
    attempts = raw.get("max_attempts", 200)
    distance = raw.get("minimum_distance", 0.08)
    configured_seed = raw.get("seed", 42)
    version = raw.get("generator_version", GENERATOR_VERSION)
    if any(isinstance(item, bool) or not isinstance(item, int) for item in (minimum, maximum, attempts, configured_seed)):
        raise _contract("generation counts and seed must be integers")
    if minimum < 1 or maximum < minimum or attempts < 1:
        raise _contract("generation candidate bounds are invalid")
    if isinstance(distance, bool) or not isinstance(distance, (int, float)) or not 0 <= float(distance) <= 1:
        raise _contract("generation minimum_distance must be between 0 and 1")
    if not isinstance(version, str) or not version.strip():
        raise _contract("generation generator_version must be a string")
    return minimum, maximum, attempts, float(distance), configured_seed, version


def _numeric(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value))


def _normalized_difference(
    pack: Mapping[str, object], name: str, left: object, right: object
) -> float:
    if _numeric(left) and _numeric(right):
        specs = _parameter_specs(pack)
        spec = specs.get(name, {})
        perturbation = spec.get("perturbation")
        if isinstance(perturbation, Mapping):
            perturb_low = perturbation.get("minimum")
            perturb_high = perturbation.get("maximum")
            if _numeric(perturb_low) and _numeric(perturb_high) and float(perturb_high) > float(perturb_low):
                declared_min, declared_max = spec.get("minimum"), spec.get("maximum")
                if _numeric(declared_min) and _numeric(declared_max):
                    baseline = (float(declared_min) + float(declared_max)) / 2.0
                else:
                    baseline = max(abs(float(left)), abs(float(right)), 1.0)
                perturbation_scale = abs(float(perturb_high) - float(perturb_low)) * max(abs(baseline), 1.0)
                if perturbation_scale > 0:
                    return min(1.0, abs(float(left) - float(right)) / perturbation_scale)
        low, high = spec.get("minimum"), spec.get("maximum")
        if _numeric(low) and _numeric(high) and float(high) > float(low):
            return min(1.0, abs(float(left) - float(right)) / (float(high) - float(low)))
        scale = max(abs(float(left)), abs(float(right)), 1.0)
        return min(1.0, abs(float(left) - float(right)) / scale)
    return 0.0 if left == right else 1.0


def candidate_distance(
    pack: Mapping[str, object],
    left: LayoutCandidate | Mapping[str, object],
    right: LayoutCandidate | Mapping[str, object],
) -> float:
    """Return a weighted normalized distance in ``[0, 1]``."""

    left_values = _parameter_values(left, "left candidate")
    right_values = _parameter_values(right, "right candidate")
    retrieval = pack.get("retrieval", {})
    features = retrieval.get("features", ()) if isinstance(retrieval, Mapping) else ()
    weighted = 0.0
    total_weight = 0.0
    if isinstance(features, list) and features:
        names_weights = tuple(
            (str(item["parameter"]), float(item.get("weight", 1.0)))
            for item in features
            if isinstance(item, Mapping) and isinstance(item.get("parameter"), str)
        )
    else:
        names_weights = tuple(
            (name, 1.0)
            for name, spec in _parameter_specs(pack).items()
            if spec.get("type") == "number"
        )
    for name, weight in names_weights:
        if weight < 0:
            continue
        difference = _normalized_difference(pack, name, left_values.get(name), right_values.get(name))
        weighted += weight * difference
        total_weight += weight
    return 0.0 if total_weight == 0 else min(1.0, weighted / total_weight)


def _perturb(value: object, spec: Mapping[str, object], rng: random.Random) -> tuple[object, bool]:
    perturbation = spec.get("perturbation")
    if not isinstance(perturbation, Mapping):
        return value, False
    if spec.get("type") == "number" and _numeric(value):
        low = perturbation.get("minimum", 0.0)
        high = perturbation.get("maximum", 0.0)
        if not _numeric(low) or not _numeric(high):
            return value, False
        result = float(value) * (1.0 + rng.uniform(float(low), float(high)))
        minimum, maximum = spec.get("minimum"), spec.get("maximum")
        if _numeric(minimum):
            result = max(result, float(minimum))
        if _numeric(maximum):
            result = min(result, float(maximum))
        return result, result != float(value)
    if spec.get("type") == "string":
        choices = spec.get("choices")
        if isinstance(choices, list) and len(choices) > 1 and rng.random() < 0.35:
            return rng.choice(choices), True
    return value, False


def _envelope_constraints(
    envelope: IndicatorEnvelope | Mapping[str, object],
    values: Mapping[str, object],
    candidate_id: str,
) -> tuple[ConstraintResult, ...]:
    """Turn envelope ranges into traceable hard constraint results."""

    raw_bounds = envelope.bounds if isinstance(envelope, IndicatorEnvelope) else envelope.get("bounds", ())
    if isinstance(raw_bounds, Mapping):
        bounds = tuple(
            (str(name), float(item["minimum"]), float(item["maximum"]))
            for name, item in raw_bounds.items()
            if isinstance(item, Mapping) and "minimum" in item and "maximum" in item
        )
    else:
        bounds = tuple(
            (str(item[0]), float(item[1]), float(item[2]))
            for item in raw_bounds
            if isinstance(item, (tuple, list)) and len(item) == 3
        )
    results: list[ConstraintResult] = []

    for name, minimum, maximum in bounds:
        actual = values.get(name)
        if not _numeric(actual):
            raise _contract(f"envelope bound parameter {name!r} is missing or non-numeric")
        numeric = float(actual)
        lower_passed = numeric >= minimum
        upper_passed = numeric <= maximum
        results.extend(
            (
                ConstraintResult(
                    id=f"{candidate_id}:envelope-{name}-min",
                    candidate_id=candidate_id,
                    constraint_id=f"envelope-{name}-min",
                    severity="hard",
                    actual=numeric,
                    operator=">=",
                    limit=minimum,
                    margin=numeric - minimum,
                    passed=lower_passed,
                    message=f"{name} must be at least {minimum}",
                ),
                ConstraintResult(
                    id=f"{candidate_id}:envelope-{name}-max",
                    candidate_id=candidate_id,
                    constraint_id=f"envelope-{name}-max",
                    severity="hard",
                    actual=numeric,
                    operator="<=",
                    limit=maximum,
                    margin=maximum - numeric,
                    passed=upper_passed,
                    message=f"{name} must be at most {maximum}",
                ),
            )
        )
    return tuple(results)


def _candidate_payload(
    pack: Mapping[str, object],
    envelope: IndicatorEnvelope | Mapping[str, object],
    references: tuple[SchemeRecord | Mapping[str, object], ...],
    values: Mapping[str, object],
    seed: int,
    generator_version: str,
) -> dict[str, object]:
    reference_revisions = tuple(
        (str(item.get("id")), int(item.get("revision", 1)))
        if isinstance(item, Mapping)
        else (item.id, item.revision)
        for item in references
    )
    envelope_hash = envelope.input_hash if isinstance(envelope, IndicatorEnvelope) else canonical_hash(envelope)
    return {
        "envelope": envelope_hash,
        "domain_pack": (str(pack.get("id")), int(pack.get("version", 1))),
        "references": reference_revisions,
        "parameters": tuple(sorted(values.items())),
        "generator_version": generator_version,
        "seed": seed,
    }


def generate_layout_candidates(
    pack: Mapping[str, object],
    envelope: IndicatorEnvelope | Mapping[str, object],
    schemes: Iterable[SchemeRecord | Mapping[str, object]],
    matches: Iterable[SimilarityMatch | Mapping[str, object]],
    seed: int | None = None,
) -> tuple[LayoutCandidate, ...]:
    """Generate bounded, feasible candidates using historical references.

    A candidate is admitted only after all hard constraints pass and after it
    is sufficiently far from every already admitted candidate.  Infeasible
    attempts are intentionally discarded and never counted toward the formal
    candidate total.
    """

    if not isinstance(pack, Mapping):
        raise _contract("domain pack must be an object")
    target = _parameter_values(envelope, "envelope")
    scheme_values = tuple(schemes)
    by_id = {_scheme_id(item): item for item in scheme_values}
    normalized_matches = tuple(_match_value(item, _match_id(item)) for item in matches)
    normalized_matches = tuple(item for item in normalized_matches if item.scheme_id in by_id)
    if not normalized_matches:
        return ()

    minimum, maximum, max_attempts, minimum_distance, configured_seed, configured_version = _generation(pack)
    actual_seed = configured_seed if seed is None else seed
    if isinstance(actual_seed, bool) or not isinstance(actual_seed, int):
        raise _contract("seed must be an integer")
    rng = random.Random(actual_seed)
    specs = _parameter_specs(pack)
    accepted: list[LayoutCandidate] = []
    seen_hashes: set[str] = set()
    for attempt in range(max_attempts):
        if len(accepted) >= maximum:
            break
        match = normalized_matches[attempt % len(normalized_matches)]
        reference = by_id[match.scheme_id]
        reference_values = _parameter_values(reference, f"scheme {match.scheme_id}")
        values: dict[str, object] = {}
        sources: dict[str, str] = {}
        # Envelope targets win.  Historical values fill only an omitted field;
        # a missing required value therefore remains a normal contract error.
        for name in specs:
            if name in target:
                values[name] = target[name]
                sources[name] = "envelope"
            elif name in reference_values:
                values[name] = reference_values[name]
                sources[name] = f"reference:{match.scheme_id}"
        for name, spec in specs.items():
            if name not in values:
                continue
            values[name], changed = _perturb(values[name], spec, rng)
            if changed:
                sources[name] = "perturbation"
        try:
            normalized = normalize_parameters(pack, values)
            # Explicitly derive here to reject arithmetic failures before
            # constructing a candidate and to retain derived geometry values.
            derived = derive_parameters(pack, normalized)
            preliminary_hash = canonical_hash(
                _candidate_payload(pack, envelope, (reference,), normalized, actual_seed, configured_version)
            )
            candidate_id = f"{pack.get('id_prefix', 'C')}-C-{preliminary_hash[:12]}"
            constraints = evaluate_constraints(pack, normalized, candidate_id) + _envelope_constraints(
                envelope, normalized, candidate_id
            )
        except ContractViolation:
            continue
        if any(not item.passed for item in constraints if item.severity == "hard"):
            continue
        input_hash = preliminary_hash
        result_payload = {
            **_candidate_payload(pack, envelope, (reference,), normalized, actual_seed, configured_version),
            "candidate_id": candidate_id,
            "constraints": constraints,
        }
        result_hash = canonical_hash(result_payload)
        if result_hash in seen_hashes:
            continue
        geometry = {
            "span_m": float(normalized.get("span_m", 0.0)),
            "wing_area_m2": float(normalized.get("wing_area_m2", 0.0)),
            "fuselage_length_m": float(normalized.get("fuselage_length_m", 0.0)),
            "chord_m": float(normalized.get("wing_area_m2", 0.0))
            / float(normalized.get("span_m", 1.0)),
        }
        candidate = LayoutCandidate(
            id=candidate_id,
            envelope_id=envelope.id if isinstance(envelope, IndicatorEnvelope) else str(envelope.get("id", "envelope")),
            domain_pack_id=str(pack.get("id")),
            domain_pack_version=int(pack.get("version", 1)),
            reference_ids=(match.scheme_id,),
            similarity_matches=(match,),
            parameters=tuple(sorted(normalized.items())),
            parameter_sources=tuple(sorted(sources.items())),
            geometry=tuple(sorted(geometry.items())),
            svg="",
            constraints=constraints,
            feasible=True,
            infeasible_reasons=(),
            status="feasible",
            generator_version=configured_version,
            seed=actual_seed,
            input_hash=input_hash,
            result_hash=result_hash,
        )
        if any(candidate_distance(pack, candidate, previous) < minimum_distance for previous in accepted):
            continue
        candidate = replace(candidate, svg=render_layout_svg(pack, candidate))
        accepted.append(candidate)
        seen_hashes.add(result_hash)

    # The attempt sequence is deterministic; retaining it communicates which
    # references seeded each candidate and makes downstream trace links stable.
    if len(accepted) < minimum:
        return ()
    return tuple(accepted)


__all__ = ["GENERATOR_VERSION", "candidate_distance", "generate_layout_candidates"]
