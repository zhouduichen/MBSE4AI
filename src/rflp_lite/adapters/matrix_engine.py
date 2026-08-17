"""Always-available built-in matrix engine."""

from __future__ import annotations

from rflp_lite.ports.diagram_engine import DiagramRenderResult


class MatrixEngine:
    engine_id = "matrix"

    def status(self) -> dict[str, object]:
        return {"engine_id": self.engine_id, "available": True, "formats": ("svg",)}

    def render(
        self, source: str, output_format: str = "svg", timeout_seconds: int = 10
    ) -> DiagramRenderResult:
        del timeout_seconds
        if output_format != "svg":
            return DiagramRenderResult(self.engine_id, False, b"", "", "内置矩阵引擎只支持 svg")
        return DiagramRenderResult(
            self.engine_id,
            True,
            source.encode("utf-8"),
            "image/svg+xml",
        )
