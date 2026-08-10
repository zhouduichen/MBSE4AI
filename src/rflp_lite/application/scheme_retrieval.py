"""Deterministic, explainable retrieval of historical concept schemes.

The first concept-design workflow does not need a vector database.  A domain
pack declares a small list of retrieval features and weights; this module
turns those declarations into a weighted, normalized distance over the fixed
``SchemeRecord`` and ``IndicatorEnvelope`` contracts.  Every feature is kept
in the explanation, including unavailable values, so a reviewer can tell why
a scheme was ranked where it was.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

from rflp_lite.domain.concept_design import IndicatorEnvelope, SchemeRecord, SimilarityMatch
from rflp_lite.domain.errors import ContractViolation


def _contract(message: str) -> ContractViolation:
    return ContractViolation(f"invalid scheme retrieval input: {message}")


def _mapping_values(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _contract(f"{label} must be an object")
    return value


def _parameters(value: object, label: str) -> dict[str, object]:
    """Convert a record's tuple parameters (or a mapping fixture) to a map."""

    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        result: dict[str, object] = {}
        for index, item in enumerate(value):
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise _contract(f"{label}[{index}] must be a name/value pair")
            key = item[0]
            if not isinstance(key, str) or not key.strip():
                raise _contract(f"{label}[{index}] name must be a non-empty string")
            result[key] = item[1]
        return result
    raise _contract(f"{label} must be a mapping or name/value pairs")


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _contract(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise _contract(f"{label} must be finite")
    return number


def _feature_specs(pack: Mapping[str, object]) -> tuple[tuple[str, float], ...]:
    retrieval = _mapping_values(pack.get("retrieval", {}), "retrieval")
    raw_features = retrieval.get("features", ())
    if not isinstance(raw_features, (tuple, list)):
        raise _contract("retrieval.features must be an array")
    features: list[tuple[str, float]] = []
    seen: set[str] = set()
    for index, raw_feature in enumerate(raw_features):
        feature = _mapping_values(raw_feature, f"retrieval.features[{index}]")
        name = feature.get("parameter")
        if not isinstance(name, str) or not name.strip():
            raise _contract(f"retrieval.features[{index}].parameter must be a string")
        if name in seen:
            raise _contract(f"retrieval feature is duplicated: {name}")
        seen.add(name)
        weight = _number(feature.get("weight"), f"retrieval.features[{index}].weight")
        if weight < 0:
            raise _contract(f"retrieval.features[{index}].weight must be non-negative")
        features.append((name, weight))
    return tuple(features)


def _parameter_spec(pack: Mapping[str, object], feature_name: str) -> Mapping[str, object]:
    raw_parameters = pack.get("parameters", ())
    if not isinstance(raw_parameters, (tuple, list)):
        raise _contract("domain pack parameters must be an array")
    for raw in raw_parameters:
        if isinstance(raw, Mapping) and raw.get("name") == feature_name:
            return raw
    # A validated pack should not reach this branch; retaining a clear error is
    # useful for callers constructing small hand-written fixtures in tests.
    raise _contract(f"retrieval feature is not a declared parameter: {feature_name}")


def _normalization_range(pack: Mapping[str, object], feature_name: str) -> tuple[float, float] | None:
    spec = _parameter_spec(pack, feature_name)
    minimum = spec.get("minimum")
    maximum = spec.get("maximum")
    if minimum is None or maximum is None:
        return None
    minimum_value = _number(minimum, f"parameter {feature_name}.minimum")
    maximum_value = _number(maximum, f"parameter {feature_name}.maximum")
    if minimum_value > maximum_value:
        raise _contract(f"parameter {feature_name} minimum must not exceed maximum")
    return minimum_value, maximum_value


def _target_values(envelope: IndicatorEnvelope | Mapping[str, object]) -> dict[str, object]:
    if isinstance(envelope, IndicatorEnvelope):
        return _parameters(envelope.parameters, "envelope.parameters")
    if isinstance(envelope, Mapping):
        raw = envelope.get("parameters", envelope)
        return _parameters(raw, "envelope.parameters")
    raise _contract("envelope must be an IndicatorEnvelope or mapping")


def _scheme_values(scheme: SchemeRecord | Mapping[str, object]) -> tuple[str, dict[str, object]]:
    if isinstance(scheme, SchemeRecord):
        return scheme.id, _parameters(scheme.parameters, f"scheme {scheme.id}.parameters")
    if isinstance(scheme, Mapping):
        identifier = scheme.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            raise _contract("scheme id must be a non-empty string")
        return identifier, _parameters(scheme.get("parameters", ()), f"scheme {identifier}.parameters")
    raise _contract("schemes must contain SchemeRecord values or mappings")


def _difference(
    pack: Mapping[str, object], feature_name: str, target: object, actual: object
) -> float:
    """Return a normalized feature difference in ``[0, 1]``.

    Numeric values use the declared parameter range.  If a pack does not
    declare a range, the absolute delta is still deterministic and is scaled
    by the larger magnitude (or one), which keeps the result bounded without
    inventing a database-wide statistic.  Non-numeric features use exact
    equality, as required for enum-like declarations.
    """

    numeric = (
        not isinstance(target, bool)
        and not isinstance(actual, bool)
        and isinstance(target, (int, float))
        and isinstance(actual, (int, float))
    )
    if not numeric:
        return 0.0 if target == actual else 1.0
    target_value = _number(target, f"envelope parameter {feature_name}")
    actual_value = _number(actual, f"scheme parameter {feature_name}")
    value_range = _normalization_range(pack, feature_name)
    if value_range is None:
        scale = max(abs(target_value), abs(actual_value), 1.0)
    else:
        scale = value_range[1] - value_range[0]
        if scale <= 0:
            return 0.0 if actual_value == target_value else 1.0
    return min(1.0, abs(actual_value - target_value) / scale)


def find_similar_schemes(
    pack: Mapping[str, object],
    envelope: IndicatorEnvelope | Mapping[str, object],
    schemes: Iterable[SchemeRecord | Mapping[str, object]],
    limit: int = 5,
) -> tuple[SimilarityMatch, ...]:
    """Rank historical schemes by weighted normalized similarity.

    The returned order is independent of source row order.  Ties are broken
    by the stable scheme ID, and every feature contributes a difference.  A
    missing target or scheme value contributes the maximum difference and is
    explicitly listed in ``SimilarityMatch.missing_features``.
    """

    if not isinstance(pack, Mapping):
        raise _contract("pack must be an object")
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise _contract("limit must be an integer")
    if limit <= 0:
        return ()

    features = _feature_specs(pack)
    target_values = _target_values(envelope)
    scored: list[tuple[float, str, SimilarityMatch]] = []
    for raw_scheme in schemes:
        scheme_id, scheme_values = _scheme_values(raw_scheme)
        weighted_distance = 0.0
        feature_differences: list[tuple[str, float]] = []
        missing_features: list[str] = []
        for feature_name, weight in features:
            target_present = feature_name in target_values
            actual_present = feature_name in scheme_values
            if not target_present or not actual_present:
                difference = 1.0
                missing_features.append(feature_name)
            else:
                difference = _difference(
                    pack, feature_name, target_values[feature_name], scheme_values[feature_name]
                )
            feature_differences.append((feature_name, difference))
            weighted_distance += weight * difference
        similarity = 1.0 / (1.0 + weighted_distance)
        match = SimilarityMatch(
            scheme_id=scheme_id,
            similarity=similarity,
            feature_differences=tuple(feature_differences),
            missing_features=tuple(missing_features),
        )
        scored.append((similarity, scheme_id, match))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return tuple(item[2] for item in scored[:limit])


__all__ = ["find_similar_schemes"]
