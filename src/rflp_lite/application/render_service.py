"""ModelGraph view compilation and export."""

from __future__ import annotations

from rflp_lite.diagrams.compiler import compile_model_view
from rflp_lite.diagrams.renderers import render_view


class RenderService:
    def __init__(self, model_service):
        self.model_service = model_service

    def view(self, project_id: str, view_id: str):
        return compile_model_view(self.model_service.graph(project_id), view_id)

    def export(self, project_id: str, view_id: str, output_format: str = "json") -> tuple[bytes, str]:
        return render_view(self.view(project_id, view_id), output_format)
