"""Ports for replaceable multidisciplinary evaluation adapters.

The application layer only depends on these small protocols.  Built-in
calculators, customer supplied simulation tools, and validated surrogate
models can therefore share the same immutable :class:`DisciplineEvaluation`
contract without coupling the application to a particular technology.
"""

from __future__ import annotations

from typing import Any, Protocol

from rflp_lite.domain.concept_design import DisciplineEvaluation, LayoutCandidate


class DisciplineAdapter(Protocol):
    """Minimal contract implemented by every discipline evaluator."""

    id: str
    version: str
    source_kind: str

    def evaluate(
        self, candidate: LayoutCandidate, profile: dict[str, Any]
    ) -> DisciplineEvaluation:
        """Evaluate one candidate using the supplied discipline profile."""


class EvaluationStorePort(Protocol):
    """Minimal cache port used by the batch evaluation application service."""

    def load_discipline_evaluation(
        self, cache_key: str
    ) -> DisciplineEvaluation | None:
        """Return a cached complete evaluation, if one exists."""

    def save_discipline_evaluation(
        self, cache_key: str, value: DisciplineEvaluation
    ) -> None:
        """Persist a complete evaluation under its deterministic cache key."""


__all__ = ["DisciplineAdapter", "EvaluationStorePort"]
