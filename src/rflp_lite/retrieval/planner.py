"""Deterministic retrieval task planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from rflp_lite.methodology.contracts import ContextBundle


@dataclass(frozen=True, slots=True)
class KnowledgeGap:
    code: str
    query: str
    description: str = ""
    required_kinds: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RetrievalTask:
    gap_code: str
    query: str
    source: str
    project_id: str
    context_hash: str


class RetrievalPlanner(Protocol):
    def plan(self, gap: KnowledgeGap, context: ContextBundle) -> tuple[RetrievalTask, ...]: ...


class DefaultRetrievalPlanner:
    """Apply the documented source priority for one knowledge gap."""

    def plan(self, gap: KnowledgeGap, context: ContextBundle) -> tuple[RetrievalTask, ...]:
        from rflp_lite.domain.canonical import canonical_hash

        context_hash = canonical_hash(context)
        return tuple(
            RetrievalTask(gap.code, gap.query, source, context.project_id, context_hash)
            for source in ("user_documents", "historical_projects", "local_fts", "web")
        )
