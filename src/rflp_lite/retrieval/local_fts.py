"""Repository-backed local FTS retrieval."""

from __future__ import annotations

from typing import Protocol

from rflp_lite.retrieval.contracts import EvidenceCandidate
from rflp_lite.retrieval.planner import RetrievalTask


class FtsRepository(Protocol):
    def search_fts(
        self, project_id: str, query: str, limit: int = 20
    ) -> tuple[dict[str, object], ...]: ...


class LocalFtsRetriever:
    def __init__(self, repository: FtsRepository):
        self.repository = repository

    def search(self, task: RetrievalTask, limit: int = 20) -> tuple[EvidenceCandidate, ...]:
        rows = self.repository.search_fts(task.project_id, task.query, limit)
        return tuple(
            EvidenceCandidate(
                id=str(row.get("region_id", row.get("entity_id", row.get("evidence_id", "")))),
                source_type=str(row.get("kind", "local_fts")),
                source_id=str(row.get("region_id", row.get("entity_id", row.get("evidence_id", "")))),
                locator=str(row.get("locator", "")),
                claim=str(row.get("name", row.get("claim", task.query))),
                excerpt=str(row.get("text", row.get("excerpt", row.get("payload", "")))),
                confidence=0.75,
            )
            for row in rows
            if str(row.get("region_id", row.get("entity_id", row.get("evidence_id", ""))))
        )
