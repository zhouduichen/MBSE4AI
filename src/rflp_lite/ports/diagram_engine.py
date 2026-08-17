"""Ports for optional professional diagram renderers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DiagramRenderResult:
    engine_id: str
    success: bool
    content: bytes
    media_type: str
    diagnostic: str = ""


class DiagramEngine(Protocol):
    engine_id: str

    def status(self) -> dict[str, object]: ...

    def render(
        self, source: str, output_format: str = "svg", timeout_seconds: int = 10
    ) -> DiagramRenderResult: ...
