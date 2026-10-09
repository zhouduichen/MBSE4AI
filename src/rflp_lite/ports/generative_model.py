"""Port contracts for schema-constrained generative model calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Mapping, Protocol


SIMPLIFIED_CHINESE_OUTPUT_INSTRUCTION = (
    "面向中国用户输出。无论输入资料使用何种语言，所有自然语言输出字段必须使用简体中文；"
    "不得因为输入是英文而用英文回答。保留 JSON 字段名、ID、固定枚举值、型号、标准编号、"
    "单位和必要专有名词原样。"
)


def add_simplified_chinese_instruction(prompt: str) -> str:
    """Prefix one LLM prompt with the product's natural-language output rule."""

    return f"{SIMPLIFIED_CHINESE_OUTPUT_INSTRUCTION}\n{str(prompt).strip()}"


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
    finish_reason: str = ""
    usage: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GenerationCallEvent:
    """One actual provider transport attempt, including hidden retries."""

    lens_id: str
    attempt_kind: str
    provider_id: str
    model_id: str
    duration_ms: int
    status: str
    usage: Mapping[str, object] = field(default_factory=dict)
    estimated_cost_usd: float | None = None


TelemetrySink = Callable[[GenerationCallEvent], None]


class GenerativeModel(Protocol):
    def complete_json(self, request: GenerationRequest) -> GenerationResponse:
        """Return a validated JSON object for one analysis lens."""
