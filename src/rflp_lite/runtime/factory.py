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
                "injected",
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
            )
        return RuntimeSelection(RuleRuntime(), "offline-rule", "offline", "rule-runtime", "offline")
