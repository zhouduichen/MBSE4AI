"""LLM-first enrichment for broad concept-design intents.

The concept workflow uses this adapter as an optional intelligence layer.  A
provider can add a concept proposal and typed parameter suggestions, but the
workflow remains useful when the provider, history, or a professional pack is
not available.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from rflp_lite.application.intelligence.project_analysis import (
    apply_project_analysis,
    build_project_analysis_request,
)
from rflp_lite.domain.canonical import canonical_json
from rflp_lite.domain.errors import RflpError
from rflp_lite.ports.generative_model import GenerativeModel


@dataclass(frozen=True, slots=True)
class ConceptLLMResult:
    state: dict[str, object]
    concept_proposal: dict[str, object]
    parameter_suggestions: tuple[dict[str, object], ...]
    status: str
    diagnostics: tuple[str, ...]
    provider_id: str = ""
    model_id: str = ""


def _clone(value: object) -> dict[str, object]:
    result = canonical_json(value)
    import json

    cloned = json.loads(result)
    return cloned if isinstance(cloned, dict) else {}


def _fallback(state: dict[str, object], message: str) -> ConceptLLMResult:
    result = _clone(state)
    result["llm_analysis"] = {}
    result["concept_enrichment"] = {
        "status": "fallback",
        "proposal": {},
        "parameter_suggestions": [],
    }
    return ConceptLLMResult(
        state=result,
        concept_proposal={},
        parameter_suggestions=(),
        status="fallback",
        diagnostics=(message,),
    )


def _normalized_config(active_config: Mapping[str, object]) -> dict[str, object] | None:
    config = dict(active_config)
    if str(config.get("kind", "remote")) == "remote" and not str(config.get("api_key", "")):
        return None
    config["response_format"] = {"type": "json_object"}
    provider_text = f'{config.get("base_url", "")} {config.get("model", "")}'.casefold()
    if "deepseek" in provider_text:
        config["thinking"] = {"type": "disabled"}
    if "11434" in provider_text or "ollama" in provider_text:
        config["reasoning_effort"] = "none"
        config["local_context_tokens"] = 8192
        config["local_max_tokens"] = 5200
    return config


def enrich_concept_input(
    state: dict[str, object],
    *,
    active_config: Mapping[str, object] | None,
    model_factory: Callable[[dict[str, object]], GenerativeModel | None],
) -> ConceptLLMResult:
    """Ask the configured LLM for a domain-neutral concept interpretation."""

    if active_config is None:
        return _fallback(state, "当前未配置可用 LLM，先保留规则解析并生成临时概念草案")
    config = _normalized_config(active_config)
    if config is None:
        return _fallback(state, "当前远程 LLM 缺少 API key，先保留规则解析并生成临时概念草案")
    try:
        model = model_factory(config)
        if model is None:
            return _fallback(state, "当前 LLM 配置不可用，先保留规则解析并生成临时概念草案")
        response = model.complete_json(build_project_analysis_request(state))
        enriched = apply_project_analysis(state, response)
        payload = response.payload
        proposal = enriched.get("concept_enrichment", {})
        proposal_payload = proposal.get("proposal", {}) if isinstance(proposal, dict) else {}
        suggestions_payload = proposal.get("parameter_suggestions", ()) if isinstance(proposal, dict) else ()
        analysis_payload = {
            key: payload.get(key)
            for key in (
                "system",
                "stakeholders",
                "concerns",
                "needs",
                "requirements",
                "scenarios",
                "architecture",
                "open_questions",
            )
            if key in payload
        }
        enriched["llm_analysis"] = {
            **analysis_payload,
            "lens_id": response.lens_id,
            "input_hash": response.input_hash,
            "output_hash": response.output_hash,
            "provider_id": response.provider_id,
            "model_id": response.model_id,
        }
        suggestions = tuple(
            dict(item) for item in suggestions_payload if isinstance(item, Mapping)
        )
        proposal_dict = dict(proposal_payload) if isinstance(proposal_payload, Mapping) else {}
        return ConceptLLMResult(
            state=enriched,
            concept_proposal=proposal_dict,
            parameter_suggestions=suggestions,
            status="completed",
            diagnostics=(),
            provider_id=response.provider_id,
            model_id=response.model_id,
        )
    except (RflpError, OSError, TypeError, ValueError, RuntimeError) as exc:
        return _fallback(state, f"LLM 概念分析未完成，已切换临时草案：{exc}")


__all__ = ["ConceptLLMResult", "enrich_concept_input"]
