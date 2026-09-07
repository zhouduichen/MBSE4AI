"""Coverage-driven, project-scoped evidence retrieval."""

from rflp_lite.retrieval.evidence import (
    EvidenceCandidate,
    EvidenceGap,
    EvidenceRetrievalResult,
    ExternalEvidenceGap,
    RetrievalEngine,
)
from rflp_lite.retrieval.planner import KnowledgeGap, RetrievalTask, RetrievalPlanner

__all__ = [
    "EvidenceCandidate",
    "EvidenceGap",
    "EvidenceRetrievalResult",
    "ExternalEvidenceGap",
    "KnowledgeGap",
    "RetrievalEngine",
    "RetrievalTask",
    "RetrievalPlanner",
]
