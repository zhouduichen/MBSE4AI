"""Concrete OpenAI-compatible RuntimePort wiring."""

from rflp_lite.adapters.openai_compatible_model import OpenAICompatibleModel
from rflp_lite.runtime.structured_model import StructuredModelRuntime


def openai_compatible_runtime(config: dict[str, object]) -> StructuredModelRuntime:
    return StructuredModelRuntime(OpenAICompatibleModel(config))
