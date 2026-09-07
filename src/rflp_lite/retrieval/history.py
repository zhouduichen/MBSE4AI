"""Historical project retrieval adapter.

Historical projects are intentionally represented by the same repository
search port.  This preserves the source priority without adding a second
database or a separate embedding service.
"""

from __future__ import annotations

from rflp_lite.retrieval.evidence import EvidenceCandidate
from rflp_lite.retrieval.planner import RetrievalTask


class HistoricalProjectRetriever:
    def __init__(self, repository):
        self.repository = repository

    def search(self, task: RetrievalTask, limit: int = 20) -> tuple[EvidenceCandidate, ...]:
        search = getattr(self.repository, "search_fts", None)
        if search is None:
            return ()
        return tuple(
            EvidenceCandidate(
                id=f"history-{row.get('entity_id', row.get('evidence_id', ''))}",
                source_type="historical_project",
                source_id=str(row.get("entity_id", row.get("evidence_id", ""))),
                locator=str(row.get("locator", "")),
                claim=str(row.get("name", row.get("claim", task.query))),
                excerpt=str(row.get("text", row.get("excerpt", row.get("payload", "")))),
                confidence=0.6,
            )
            for row in search(task.project_id, task.query, limit)
        )
