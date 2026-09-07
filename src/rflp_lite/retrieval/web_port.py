"""Optional external retrieval port."""

from __future__ import annotations

from typing import Protocol

from rflp_lite.retrieval.evidence import EvidenceCandidate
from rflp_lite.retrieval.planner import RetrievalTask


class WebRetriever(Protocol):
    def search(self, task: RetrievalTask) -> tuple[EvidenceCandidate, ...]: ...
