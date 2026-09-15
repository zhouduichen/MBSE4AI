"""Runtime selection for one analysis run.

The web process owns the settings service, but a runtime is selected at the
moment an analysis starts.  This matters when an operator activates a profile
without restarting the process and keeps the selected provider/model attached
to the run ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping, MutableMapping

from rflp_lite.methodology.contracts import TaskRuntime
from rflp_lite.ports.generative_model import GenerativeModel
from rflp_lite.runtime.openai_compatible import openai_compatible_runtime
from rflp_lite.runtime.rule_based import RuleRuntime


DEFAULT_CONTEXT_WINDOW = 8192
DEFAULT_MAX_OUTPUT_TOKENS = 4096


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
    controller_model: GenerativeModel | None = None

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
                str(config.get("provider_id", config.get("provider", "injected"))) if config else "injected",
                str(config.get("model", "injected")) if config else "injected",
                "configured" if config else "injected",
                _int_value(config, "context_window") if config else None,
                _int_value(config, "max_output_tokens") if config else None,
                _float_value(config, "temperature", 0.0) if config else 0.0,
                _int_value(config, "seed") if config else None,
                str(config.get("structured_output_mode", "json_schema")) if config else "json_schema",
                _eligible_controller_model(runtime_override),
            )
        if config:
            profile_id = str(config.get("id", "")).strip()
            provider_id = str(config.get("provider_id", config.get("provider", profile_id))).strip()
            model_id = str(config.get("model", "")).strip()
            if not profile_id or not model_id:
                raise ValueError("active LLM profile must contain id and model")
            if not bool(config.get("enabled", True)):
                raise ValueError("active LLM profile is disabled")
            context_window = _int_value(config, "context_window")
            max_output_tokens = _int_value(config, "max_output_tokens")
            if context_window is None:
                context_window = DEFAULT_CONTEXT_WINDOW
            if max_output_tokens is None:
                max_output_tokens = DEFAULT_MAX_OUTPUT_TOKENS
            runtime_config = dict(config)
            _set_if_missing(runtime_config, "context_window", context_window)
            _set_if_missing(runtime_config, "local_context_tokens", context_window)
            _set_if_missing(runtime_config, "max_output_tokens", max_output_tokens)
            _set_if_missing(runtime_config, "local_max_tokens", max_output_tokens)
            runtime = openai_compatible_runtime(runtime_config)
            return RuntimeSelection(
                runtime,
                profile_id,
                provider_id or "openai-compatible",
                model_id,
                "configured",
                context_window,
                max_output_tokens,
                _float_value(config, "temperature", 0.0),
                _int_value(config, "seed"),
                str(config.get("structured_output_mode", "json_schema")),
                _eligible_controller_model(runtime),
            )
        return RuntimeSelection(RuleRuntime(), "offline-rule", "offline", "rule-runtime", "offline")


def _eligible_controller_model(runtime: object) -> GenerativeModel | None:
    model = getattr(runtime, "model", None)
    return model if bool(getattr(model, "supports_controller_proposals", False)) else None


def _int_value(config: Mapping[str, object] | None, name: str) -> int | None:
    if not config or config.get(name) is None or config.get(name) == "":
        return None
    try:
        return int(config[name])
    except (TypeError, ValueError):
        return None


def _set_if_missing(config: MutableMapping[str, object], name: str, value: int) -> None:
    if config.get(name) is None or config.get(name) == "":
        config[name] = value


def _float_value(config: Mapping[str, object] | None, name: str, default: float) -> float:
    if not config or config.get(name) is None or config.get(name) == "":
        return default
    try:
        return float(config[name])
    except (TypeError, ValueError):
        return default
