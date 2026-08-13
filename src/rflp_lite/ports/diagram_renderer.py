"""Port contract for deterministic diagram rendering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from rflp_lite.domain.diagram_spec import DiagramSpec


@dataclass(frozen=True, slots=True)
class RenderedDiagram:
    diagram_id: str
    content_type: str
    extension: str
    content: bytes
    warnings: tuple[str, ...] = ()


class DiagramRenderer(Protocol):
    def render(self, spec: DiagramSpec) -> RenderedDiagram:
        raise NotImplementedError
