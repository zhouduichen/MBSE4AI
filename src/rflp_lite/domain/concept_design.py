"""Stable core records for concept-layout design and MDO.

The records in this module deliberately contain only platform concepts.  A
domain pack may add values under ``extensions`` (or inside parameter tuples),
but it cannot add columns to these contracts.  Keeping the records immutable
also makes them safe to hash and to persist as canonical JSON.
"""

from __future__ import annotations

from dataclasses import dataclass


KeyValue = tuple[str, object]


@dataclass(frozen=True, slots=True)
class SchemeRecord:
    id: str
    object_type: str
    schema_version: int
    domain_pack_id: str
    domain_pack_version: int
    revision: int
    status: str
    source: str
    parameters: tuple[KeyValue, ...]
    extensions: tuple[KeyValue, ...]
    content_hash: str


@dataclass(frozen=True, slots=True)
class IndicatorEnvelope:
    id: str
    object_type: str
    schema_version: int
    domain_pack_id: str
    domain_pack_version: int
    revision: int
    status: str
    source_requirement_ids: tuple[str, ...]
    parameters: tuple[KeyValue, ...]
    bounds: tuple[tuple[str, float, float], ...]
    input_hash: str


@dataclass(frozen=True, slots=True)
class ConstraintResult:
    id: str
    candidate_id: str
    constraint_id: str
    severity: str
    actual: float
    operator: str
    limit: float
    margin: float
    passed: bool
    message: str


@dataclass(frozen=True, slots=True)
class SimilarityMatch:
    scheme_id: str
    similarity: float
    feature_differences: tuple[tuple[str, float], ...]
    missing_features: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LayoutCandidate:
    id: str
    envelope_id: str
    domain_pack_id: str
    domain_pack_version: int
    reference_ids: tuple[str, ...]
    similarity_matches: tuple[SimilarityMatch, ...]
    parameters: tuple[KeyValue, ...]
    parameter_sources: tuple[tuple[str, str], ...]
    geometry: tuple[KeyValue, ...]
    svg: str
    constraints: tuple[ConstraintResult, ...]
    feasible: bool
    infeasible_reasons: tuple[str, ...]
    status: str
    generator_version: str
    seed: int
    input_hash: str
    result_hash: str


@dataclass(frozen=True, slots=True)
class DisciplineEvaluation:
    id: str
    candidate_id: str
    discipline: str
    adapter_id: str
    adapter_version: str
    source_kind: str
    input_hash: str
    output_hash: str
    metrics: tuple[KeyValue, ...]
    status: str
    evidence_status: str
    validity: tuple[KeyValue, ...]
    diagnostics: tuple[str, ...]
    log_ref: str
    implementation_hash: str = ""
    approval_profile_hash: str = ""
    approval_diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OptimizationRun:
    id: str
    envelope_id: str
    domain_pack_id: str
    domain_pack_version: int
    candidate_ids: tuple[str, ...]
    evaluation_ids: tuple[str, ...]
    iteration_records: tuple[KeyValue, ...]
    front_candidate_ids: tuple[str, ...]
    seed: int
    stop_reason: str
    input_hash: str
    result_hash: str
    status: str
    evidence_status: str


__all__ = [
    "ConstraintResult",
    "DisciplineEvaluation",
    "IndicatorEnvelope",
    "KeyValue",
    "LayoutCandidate",
    "OptimizationRun",
    "SchemeRecord",
    "SimilarityMatch",
]

