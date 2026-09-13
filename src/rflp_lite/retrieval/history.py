"""Historical project retrieval adapter.

Historical projects are intentionally represented by the same repository
search port.  This preserves the source priority without adding a second
database or a separate embedding service.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from rflp_lite.retrieval.contracts import EvidenceCandidate
from rflp_lite.retrieval.planner import RetrievalTask


class HistoricalProjectRetriever:
    def __init__(
        self,
        repository,
        *,
        project_sources: Sequence[tuple[str, Path]] | None = None,
        repository_factory: Callable[[Path], object] | None = None,
    ):
        self.repository = repository
        self.project_sources = tuple(project_sources)
        self.repository_factory = repository_factory

    def search(self, task: RetrievalTask, limit: int = 20) -> tuple[EvidenceCandidate, ...]:
        if self.project_sources is None:
            return self._search_repository(self.repository, task, limit, task.project_id)
        candidates: list[EvidenceCandidate] = []
        for project_id, database_path in self.project_sources:
            if project_id == task.project_id or not database_path.is_file():
                continue
            repository = None
            try:
                if self.repository_factory is None:
                    continue
                repository = self.repository_factory(database_path)
                candidates.extend(self._search_repository(repository, task, limit, project_id))
            except (OSError, RuntimeError, ValueError):
                continue
            finally:
                close = getattr(repository, "close", None)
                if callable(close):
                    close()
            if len(candidates) >= limit:
                break
        return tuple(candidates[: max(1, int(limit))])

    @staticmethod
    def _search_repository(repository, task, limit: int, project_id: str):
        search = getattr(repository, "search_fts", None)
        if search is None:
            return ()
        result = []
        for row in search(project_id, task.query, limit):
            source_key = str(row.get("entity_id", row.get("region_id", row.get("evidence_id", ""))))
            if not source_key:
                continue
            result.append(
                EvidenceCandidate(
                    id=f"history-{project_id}-{source_key}",
                    source_type="historical_project",
                    source_id=f"{project_id}:{source_key}",
                    locator=f"{project_id}:{row.get('locator', '')}",
                    claim=str(row.get("name", row.get("claim", task.query))),
                    excerpt=str(row.get("text", row.get("excerpt", row.get("payload", "")))),
                    confidence=0.6,
                )
            )
        return tuple(result)
