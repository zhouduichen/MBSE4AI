"""Coverage-driven, project-scoped evidence retrieval."""

from rflp_lite.retrieval.contracts import EvidenceCandidate
from rflp_lite.retrieval.evidence import (
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
