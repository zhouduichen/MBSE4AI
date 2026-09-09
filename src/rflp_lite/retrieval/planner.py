"""Deterministic retrieval task planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from rflp_lite.methodology.contracts import ContextBundle, TaskSpec


@dataclass(frozen=True, slots=True)
class KnowledgeGap:
    code: str
    query: str
    description: str = ""
    required_kinds: tuple[str, ...] = ()


def build_gap_query(
    task: TaskSpec,
    root_entities,
    issue: KnowledgeGap | object | None,
    context: ContextBundle,
) -> str:
    """Build a stable retrieval query from the real gap and local model terms."""

    terms: list[str] = [task.id.replace("_", " ")]
    for entity in sorted(root_entities, key=lambda item: item.id):
        terms.append(entity.meta.name)
        for key in ("obligation", "candidate_type", "constraints", "rationale", "description"):
            value = entity.payload.get(key)
            if value:
                terms.append(str(value))
    if isinstance(issue, KnowledgeGap):
        terms.extend(item for item in (issue.code, issue.description, issue.query) if item)
    elif issue is not None:
        terms.append(str(issue))
    terms.extend(str(kind) for kind in getattr(issue, "required_kinds", ()) if str(kind))
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        clean = " ".join(str(term).split()).strip()
        if clean and clean.casefold() not in seen:
            seen.add(clean.casefold())
            deduped.append(clean)
    return " ".join(deduped)


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
