"""Evidence ingestion, search, and optional external retrieval."""

from __future__ import annotations

from rflp_lite.methodology.contracts import ContextBundle
from rflp_lite.retrieval.evidence import EvidenceRetrievalResult, RetrievalEngine
from rflp_lite.retrieval.planner import KnowledgeGap


class EvidenceService:
    def __init__(self, repository, *, web_retriever=None, retrieval_engine=None):
        self.repository = repository
        self.retrieval = retrieval_engine or RetrievalEngine(repository, web_retriever=web_retriever)

    def list(self, project_id: str):
        return self.repository.list_evidence(project_id)

    def search(self, gap: KnowledgeGap, context: ContextBundle) -> EvidenceRetrievalResult:
        result = self.retrieval.retrieve(gap, context)
        for candidate in result.candidates:
            self.repository.save_evidence(context.project_id, self.retrieval.to_evidence(candidate))
        return result
