"""Port contracts for schema-constrained generative model calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    lens_id: str
    system_prompt: str
    user_payload: dict[str, object]
    response_schema: dict[str, object]
    max_tokens: int = 2000


@dataclass(frozen=True, slots=True)
class GenerationResponse:
    lens_id: str
    payload: dict[str, object]
    input_hash: str
    output_hash: str
    repaired: bool
    provider_id: str = ""
    model_id: str = ""
    template_version: str = "v1"
    duration_ms: int = 0
    status: str = "completed"


class GenerativeModel(Protocol):
    def complete_json(self, request: GenerationRequest) -> GenerationResponse:
        """Return a validated JSON object for one analysis lens."""

