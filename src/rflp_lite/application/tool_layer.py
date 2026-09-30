"""Bounded engineering tools that the Systems Engineering Controller can call."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping

from rflp_lite.methodology.contracts import ContextBundle
from rflp_lite.retrieval.contracts import EvidenceCandidate
from rflp_lite.retrieval.evidence import EvidenceRetrievalResult, RetrievalEngine
from rflp_lite.retrieval.planner import KnowledgeGap


@dataclass(frozen=True, slots=True)
class ToolResult:
    tool_id: str
    status: str
    query: str = ""
    evidence: tuple[Mapping[str, object], ...] = ()
    gaps: tuple[Mapping[str, object], ...] = ()
    diagnostics: tuple[str, ...] = ()

    def as_dict(self) -> Mapping[str, object]:
        return {
            "tool_id": self.tool_id,
            "status": self.status,
            "query": self.query,
            "evidence": [dict(item) for item in self.evidence],
            "gaps": [dict(item) for item in self.gaps],
            "diagnostics": list(self.diagnostics),
        }


class EngineeringToolLayer:
    """Expose deterministic, auditable tools without letting tools mutate ModelGraph."""

    def __init__(self, repository, *, retrieval_engine: RetrievalEngine | None = None):
        self.repository = repository
        self.retrieval = retrieval_engine or RetrievalEngine(repository)

    def collect_evidence(
        self,
        project_id: str,
        graph,
        action: Mapping[str, object],
    ) -> ToolResult:
        entity_ids = tuple(str(item) for item in action.get("entity_ids", ()) if str(item))
        entities = tuple(
            graph.entity_index[entity_id]
            for entity_id in entity_ids
            if entity_id in graph.entity_index
        )
        task_id = str(action.get("task_id", "controller.evidence")).strip()
        reason = " ".join(str(action.get("reason", "")).split()).strip()
        query_terms = [task_id.replace("_", " "), reason]
        query_terms.extend(entity.meta.name for entity in entities)
        query = " ".join(term for term in query_terms if term).strip()
        context = ContextBundle(
            project_id,
            task_id,
            graph.revision,
            tuple(graph.entities),
            graph.relations,
            tuple(self.repository.list_evidence(project_id)),
        )
        gap = KnowledgeGap(
            f"controller.{action.get('id', task_id)}",
            query,
            reason,
            tuple(entity.kind.value for entity in entities),
        )
        try:
            result = self.retrieval.retrieve(gap, context)
        except Exception as exc:
            return ToolResult(
                "evidence.search",
                "failed",
                query,
                diagnostics=(str(exc),),
            )
        evidence = tuple(
            self.retrieval.to_evidence(candidate)
            for candidate in result.candidates
            if isinstance(candidate, EvidenceCandidate)
        )
        for item in evidence:
            self.repository.save_evidence(project_id, item)
        return ToolResult(
            "evidence.search",
            "completed" if evidence else "no_result",
            query,
            evidence,
            tuple(_gap_dict(item) for item in result.gaps),
            (),
        )


def _gap_dict(gap: object) -> Mapping[str, object]:
    return {
        "code": str(getattr(gap, "code", "tool_gap")),
        "message": str(getattr(gap, "message", gap)),
        "workflow_blocked": bool(getattr(gap, "workflow_blocked", False)),
    }
