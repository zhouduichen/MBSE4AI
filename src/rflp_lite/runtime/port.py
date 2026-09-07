"""Runtime port; Methodology does not depend on a provider SDK."""

from __future__ import annotations

from typing import Protocol

from rflp_lite.methodology.contracts import TaskExecutionRequest, TaskExecutionResponse


class RuntimePort(Protocol):
    def execute(self, request: TaskExecutionRequest) -> TaskExecutionResponse: ...
