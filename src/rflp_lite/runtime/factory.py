"""Runtime selection for one analysis run.

The web process owns the settings service, but a runtime is selected at the
moment an analysis starts.  This matters when an operator activates a profile
without restarting the process and keeps the selected provider/model attached
to the run ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from rflp_lite.methodology.contracts import TaskRuntime
from rflp_lite.runtime.openai_compatible import openai_compatible_runtime
from rflp_lite.runtime.rule_based import RuleRuntime


@dataclass(frozen=True, slots=True)
class RuntimeSelection:
    runtime: TaskRuntime
    profile_id: str
    provider_id: str
    model_id: str
    mode: str
    context_window: int | None = None
    max_output_tokens: int | None = None
    temperature: float = 0.0
    seed: int | None = None
    structured_output_mode: str = "json_schema"

    @property
    def configured(self) -> bool:
        return self.mode == "configured"


class RuntimeFactory:
    """Build the runtime that is actually used by an analysis invocation."""

    def select(
        self,
        config: Mapping[str, object] | None,
        *,
        runtime_override: TaskRuntime | None = None,
    ) -> RuntimeSelection:
        if runtime_override is not None:
            return RuntimeSelection(
                runtime_override,
                str(config.get("id", "injected")) if config else "injected",
                str(config.get("provider_id", "injected")) if config else "injected",
                str(config.get("model", "injected")) if config else "injected",
                "configured" if config else "injected",
                _int_value(config, "context_window") if config else None,
                _int_value(config, "max_output_tokens") if config else None,
                _float_value(config, "temperature", 0.0) if config else 0.0,
                _int_value(config, "seed") if config else None,
                str(config.get("structured_output_mode", "json_schema")) if config else "json_schema",
            )
        if config:
            profile_id = str(config.get("id", "")).strip()
            provider_id = str(config.get("provider_id", config.get("provider", profile_id))).strip()
            model_id = str(config.get("model", "")).strip()
            if not profile_id or not model_id:
                raise ValueError("active LLM profile must contain id and model")
            if not bool(config.get("enabled", True)):
                raise ValueError("active LLM profile is disabled")
            return RuntimeSelection(
                openai_compatible_runtime(dict(config)),
                profile_id,
                provider_id or "openai-compatible",
                model_id,
                "configured",
                _int_value(config, "context_window"),
                _int_value(config, "max_output_tokens"),
                _float_value(config, "temperature", 0.0),
                _int_value(config, "seed"),
                str(config.get("structured_output_mode", "json_schema")),
            )
        return RuntimeSelection(RuleRuntime(), "offline-rule", "offline", "rule-runtime", "offline")


def _int_value(config: Mapping[str, object] | None, name: str) -> int | None:
    if not config or config.get(name) is None or config.get(name) == "":
        return None
    try:
        return int(config[name])
    except (TypeError, ValueError):
        return None


def _float_value(config: Mapping[str, object] | None, name: str, default: float) -> float:
    if not config or config.get(name) is None or config.get(name) == "":
        return default
    try:
        return float(config[name])
    except (TypeError, ValueError):
        return default
