"""Evidence candidates and optional-source failure semantics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.methodology.contracts import ContextBundle
from rflp_lite.retrieval.planner import DefaultRetrievalPlanner, KnowledgeGap, RetrievalTask, RetrievalPlanner


@dataclass(frozen=True, slots=True)
class EvidenceCandidate:
    id: str
    source_type: str
    source_id: str
    locator: str
    claim: str
    excerpt: str
    confidence: float = 0.5


@dataclass(frozen=True, slots=True)
class EvidenceGap:
    code: str
    message: str
    workflow_blocked: bool = False
    confidence_penalty: float = 0.0


@dataclass(frozen=True, slots=True)
class ExternalEvidenceGap(EvidenceGap):
    source: str = "web"


@dataclass(frozen=True, slots=True)
class EvidenceRetrievalResult:
    candidates: tuple[EvidenceCandidate, ...] = ()
    gaps: tuple[EvidenceGap, ...] = ()
    workflow_blocked: bool = False
    confidence: float = 1.0


class CandidateRetriever(Protocol):
    def search(self, task: RetrievalTask) -> tuple[EvidenceCandidate, ...]: ...


class RetrievalEngine:
    """Run prioritized retrieval while keeping Web optional."""

    def __init__(
        self,
        repository,
        *,
        planner: RetrievalPlanner | None = None,
        web_retriever: CandidateRetriever | None = None,
        historical_retriever: CandidateRetriever | None = None,
        document_retriever: CandidateRetriever | None = None,
        max_rounds: int = 2,
    ) -> None:
        from rflp_lite.retrieval.history import HistoricalProjectRetriever
        from rflp_lite.retrieval.local_fts import LocalFtsRetriever

        self.planner = planner or DefaultRetrievalPlanner()
        self.local = LocalFtsRetriever(repository)
        self.historical = historical_retriever or HistoricalProjectRetriever(repository)
        self.documents = document_retriever or self.local
        self.web = web_retriever
        self.max_rounds = max(1, max_rounds)

    def retrieve(self, gap: KnowledgeGap, context: ContextBundle) -> EvidenceRetrievalResult:
        candidates: list[EvidenceCandidate] = []
        gaps: list[EvidenceGap] = []
        low_yield_rounds = 0
        confidence = 1.0
        handlers: dict[str, CandidateRetriever] = {
            "user_documents": self.documents,
            "historical_projects": self.historical,
            "local_fts": self.local,
        }
        for task in self.planner.plan(gap, context):
            if task.source == "web":
                if self.web is None:
                    gaps.append(ExternalEvidenceGap("external_evidence_gap", "Web 检索未配置", False, 0.15))
                    confidence = max(0.0, confidence - 0.15)
                    continue
                try:
                    found = self.web.search(task)
                except Exception as exc:
                    gaps.append(ExternalEvidenceGap("external_evidence_gap", f"Web 检索失败: {exc}", False, 0.2))
                    confidence = max(0.0, confidence - 0.2)
                    continue
            else:
                found = handlers[task.source].search(task)
            if found:
                candidates.extend(found)
                low_yield_rounds = 0
            else:
                low_yield_rounds += 1
            if low_yield_rounds >= self.max_rounds:
                break
        unique: dict[str, EvidenceCandidate] = {item.id: item for item in candidates}
        return EvidenceRetrievalResult(
            tuple(unique.values()), tuple(gaps), False, confidence
        )

    @staticmethod
    def to_evidence(candidate: EvidenceCandidate) -> dict[str, object]:
        return {
            "id": f"evidence-{canonical_hash(candidate.id)[:16]}",
            "source_type": candidate.source_type,
            "source_id": candidate.source_id,
            "locator": candidate.locator,
            "claim": candidate.claim,
            "excerpt": candidate.excerpt,
            "relevance": candidate.confidence,
        }
