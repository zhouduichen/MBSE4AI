"""Explicit configured-model profile resolution for A–E benchmark runs."""

from __future__ import annotations

from collections.abc import Mapping

from rflp_lite.application.llm_profiles import LLMProfileService


LLM_METRICS = (
    "requirement_precision",
    "requirement_recall",
    "requirement_atomicity",
    "requirement_verifiability",
    "unsupported_numeric_claim_rate",
    "trace_accuracy",
    "RFLP_coverage",
    "evidence_faithfulness",
    "verification_quality",
    "hallucinated_entity_rate",
)


def resolve_profile(profile_id: str, service: LLMProfileService | None = None) -> dict[str, object]:
    """Resolve an explicit local profile without exposing credentials in reports."""

    requested = str(profile_id).strip()
    if not requested:
        raise ValueError("--profile is required for --track llm")
    service = service or LLMProfileService()
    snapshot = service.snapshot()
    profiles = snapshot.get("profiles", ())
    profile = next(
        (
            item
            for item in profiles
            if isinstance(item, Mapping) and str(item.get("id", "")) == requested
        ),
        None,
    )
    if not isinstance(profile, Mapping):
        raise ValueError(f"LLM profile not found: {requested}")
    config = service.config_for(dict(profile))
    if str(config.get("kind", "")).casefold() == "remote" and not str(config.get("api_key", "")):
        raise ValueError(f"LLM profile has no configured API key: {requested}")
    return config


__all__ = ["LLM_METRICS", "resolve_profile"]
