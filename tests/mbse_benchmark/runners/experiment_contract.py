"""Shared experiment-boundary value objects for the A–E benchmark."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from statistics import mean, stdev
from typing import Mapping, Sequence

from rflp_lite.domain.canonical import canonical_json
from rflp_lite.ports.generative_model import GenerationCallEvent, TelemetrySink


_EVALUATOR_KEYS = frozenset({
    "evaluation_spec",
    "evaluation_spec_hash",
    "expected",
    "expected_graph",
    "ground_truth",
    "reference_graph",
})


@dataclass(frozen=True, slots=True)
class ExperimentTelemetry:
    call_count: int
    initial_call_count: int
    repair_call_count: int
    failed_call_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    provider_latency_ms: int
    wall_latency_ms: int
    input_cost_per_1m_tokens: float | None
    output_cost_per_1m_tokens: float | None
    estimated_cost_usd: float | None
    cost_status: str
    comparison_mode: str
    total_output_token_budget: int | None
    budget_exhausted: bool

    @classmethod
    def from_events(
        cls,
        events: Sequence[GenerationCallEvent],
        *,
        wall_latency_ms: int = 0,
        comparison_mode: str = "natural",
        total_output_token_budget: int | None = None,
        input_cost_per_1m_tokens: float | None = None,
        output_cost_per_1m_tokens: float | None = None,
    ) -> "ExperimentTelemetry":
        input_tokens = sum(_usage_int(event.usage, "input_tokens", "prompt_tokens") for event in events)
        output_tokens = sum(_usage_int(event.usage, "output_tokens", "completion_tokens") for event in events)
        total_tokens = sum(
            _usage_int(event.usage, "total_tokens") or (
                _usage_int(event.usage, "input_tokens", "prompt_tokens")
                + _usage_int(event.usage, "output_tokens", "completion_tokens")
            )
            for event in events
        )
        event_costs = [event.estimated_cost_usd for event in events if event.estimated_cost_usd is not None]
        if event_costs:
            estimated_cost = round(sum(event_costs), 8)
            cost_status = "available"
        elif input_cost_per_1m_tokens is not None and output_cost_per_1m_tokens is not None:
            estimated_cost = round(
                input_tokens * input_cost_per_1m_tokens / 1_000_000
                + output_tokens * output_cost_per_1m_tokens / 1_000_000,
                8,
            )
            cost_status = "available"
        else:
            estimated_cost = None
            cost_status = "unavailable"
        return cls(
            call_count=len(events),
            initial_call_count=sum(event.attempt_kind == "initial" for event in events),
            repair_call_count=sum(event.attempt_kind != "initial" for event in events),
            failed_call_count=sum(event.status != "completed" for event in events),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            provider_latency_ms=sum(max(0, int(event.duration_ms)) for event in events),
            wall_latency_ms=max(0, int(wall_latency_ms)),
            input_cost_per_1m_tokens=input_cost_per_1m_tokens,
            output_cost_per_1m_tokens=output_cost_per_1m_tokens,
            estimated_cost_usd=estimated_cost,
            cost_status=cost_status,
            comparison_mode=comparison_mode,
            total_output_token_budget=total_output_token_budget,
            budget_exhausted=(
                total_output_token_budget is not None
                and output_tokens >= max(0, int(total_output_token_budget))
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "call_count": self.call_count,
            "initial_call_count": self.initial_call_count,
            "repair_call_count": self.repair_call_count,
            "failed_call_count": self.failed_call_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "provider_latency_ms": self.provider_latency_ms,
            "wall_latency_ms": self.wall_latency_ms,
            "input_cost_per_1m_tokens": self.input_cost_per_1m_tokens,
            "output_cost_per_1m_tokens": self.output_cost_per_1m_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
            "cost_status": self.cost_status,
            "comparison_mode": self.comparison_mode,
            "total_output_token_budget": self.total_output_token_budget,
            "budget_exhausted": self.budget_exhausted,
        }


def _usage_int(usage: Mapping[str, object], *keys: str) -> int:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return max(0, int(value))
    return 0


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
    "ExperimentTelemetry",
    "GenerationCallEvent",
    "TelemetrySink",
    "assert_model_visible_payload",
    "input_sha256",
    "summarize_repeats",
]
