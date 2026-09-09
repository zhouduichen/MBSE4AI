"""Shared input to executable methodology validators."""

from __future__ import annotations

from dataclasses import dataclass

from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.contracts import ContextBundle, TaskExecutionResponse, TaskSpec


@dataclass(frozen=True, slots=True)
class ValidationContext:
    project_id: str
    task: TaskSpec
    graph: ModelGraph
    context: ContextBundle
    response: TaskExecutionResponse
