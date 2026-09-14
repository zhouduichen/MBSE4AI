"""Read-only application projection for a complete lifecycle result."""

from __future__ import annotations

from collections.abc import Mapping

from rflp_lite.application.model_generation import build_traceability_summary
from rflp_lite.methodology.controller import SystemsEngineeringController
from rflp_lite.methodology.engine import MethodologyEngine


class PipelineReportService:
    """Project the current ModelGraph into user-facing engineering findings."""

    def __init__(
        self,
        repository,
        *,
        methodology_engine: MethodologyEngine | None = None,
        controller: SystemsEngineeringController | None = None,
    ) -> None:
        self.repository = repository
        self.methodology_engine = methodology_engine or MethodologyEngine()
        self.controller = controller or SystemsEngineeringController(self.methodology_engine)

    def build(self, project_id: str) -> Mapping[str, object]:
        """Return a deterministic report without writing or invoking a model."""

        graph = self.repository.load_graph(project_id)
        traceability = build_traceability_summary(graph)
        methodology = self.methodology_engine.analyze(graph)
        controller = self.controller.plan(graph, methodology)
        return {
            "traceability": traceability.as_dict(),
            "methodology": methodology.as_dict(),
            "controller": controller.as_dict(),
            "report_revision": graph.revision,
            "report_snapshot_hash": graph.snapshot_hash,
        }
