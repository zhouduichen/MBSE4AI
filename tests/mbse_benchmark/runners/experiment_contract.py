"""Shared experiment-boundary value objects for the A–E benchmark."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from statistics import mean, stdev
from typing import Any, Mapping, Sequence

from rflp_lite.domain.canonical import canonical_json


_EVALUATOR_KEYS = frozenset({
    "evaluation_spec",
    "evaluation_spec_hash",
    "expected",
    "expected_graph",
    "ground_truth",
    "reference_graph",
})


@dataclass(frozen=True, slots=True)
class BenchmarkInputEnvelope:
    """The exact case bytes that every scenario is allowed to observe."""

    case_id: str
    payload: Mapping[str, object]
    canonical_bytes: bytes
    input_hash: str

    @classmethod
    def from_case(cls, case: Mapping[str, object]) -> "BenchmarkInputEnvelope":
        payload = dict(case)
        case_id = str(payload.get("case_id", "")).strip()
        if not case_id:
            raise ValueError("benchmark input requires case_id")
        encoded = canonical_json(payload).encode("utf-8")
        return cls(case_id, payload, encoded, hashlib.sha256(encoded).hexdigest())


@dataclass(frozen=True, slots=True)
class EvaluationSpec:
    """Ground truth that is owned exclusively by ``ExternalEvaluator``."""

    payload: Mapping[str, object]
    canonical_bytes: bytes
    evaluation_spec_hash: str

    @classmethod
    def from_expectations(cls, expectations: Mapping[str, object]) -> "EvaluationSpec":
        payload = dict(expectations)
        encoded = canonical_json(payload).encode("utf-8")
        return cls(payload, encoded, hashlib.sha256(encoded).hexdigest())

    def as_dict(self) -> dict[str, object]:
        return dict(self.payload)


def assert_model_visible_payload(payload: object, evaluation_spec: EvaluationSpec) -> None:
    """Reject evaluator-only values before a request reaches a model."""

    if payload is evaluation_spec or payload is evaluation_spec.payload:
        raise ValueError("evaluator-only EvaluationSpec cannot be model-visible")
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if str(key).casefold() in _EVALUATOR_KEYS:
                raise ValueError(f"evaluator-only key is model-visible: {key}")
            assert_model_visible_payload(value, evaluation_spec)
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            assert_model_visible_payload(value, evaluation_spec)


def input_sha256(envelope: BenchmarkInputEnvelope) -> str:
    return hashlib.sha256(envelope.canonical_bytes).hexdigest()


def summarize_repeats(records: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Summarize numeric repeat fields without treating missing values as zero."""

    values_by_key: dict[str, list[float]] = {}
    for record in records:
        for key, value in record.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values_by_key.setdefault(str(key), []).append(float(value))
    result: dict[str, object] = {}
    for key, values in values_by_key.items():
        count = len(values)
        average = mean(values)
        deviation = stdev(values) if count >= 2 else 0.0
        margin = 1.96 * deviation / math.sqrt(count) if count >= 2 else 0.0
        result[key] = {
            "count": count,
            "mean": round(average, 6),
            "std": round(deviation, 6),
            "ci95": [round(average - margin, 6), round(average + margin, 6)],
        }
    return result


__all__ = [
    "BenchmarkInputEnvelope",
    "EvaluationSpec",
    "assert_model_visible_payload",
    "input_sha256",
    "summarize_repeats",
]
