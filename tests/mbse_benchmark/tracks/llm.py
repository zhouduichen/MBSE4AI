"""Explicit LLM track and same-input bare-model baseline."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
import re
from typing import Any

from rflp_lite.adapters.openai_compatible_model import OpenAICompatibleModel
from rflp_lite.application.llm_profiles import LLMProfileService
from rflp_lite.ports.generative_model import GenerationRequest


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

_BARE_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["requirements"],
    "properties": {
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "statement"],
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "statement": {"type": "string", "minLength": 1},
                    "verification_method": {"type": "string"},
                    "evidence": {"type": "string"},
                },
            },
        },
    },
}


def resolve_profile(profile_id: str, service: LLMProfileService | None = None) -> dict[str, object]:
    """Resolve an explicit local profile without exposing credentials in reports."""

    requested = str(profile_id).strip()
    if not requested:
        raise ValueError("--profile is required for --track llm")
    service = service or LLMProfileService()
    snapshot = service.snapshot()
    profiles = snapshot.get("profiles", ())
    profile = next((item for item in profiles if isinstance(item, Mapping) and str(item.get("id", "")) == requested), None)
    if not isinstance(profile, Mapping):
        raise ValueError(f"LLM profile not found: {requested}")
    config = service.config_for(dict(profile))
    if str(config.get("kind", "")).casefold() == "remote" and not str(config.get("api_key", "")):
        raise ValueError(f"LLM profile has no configured API key: {requested}")
    return config


def _normalize(value: object) -> str:
    text = str(value or "").casefold()
    return re.sub(r"[\s\u3000，。；、：:,.!?！？()（）/\\_\-]+", "", text)


def _matches(expected: str, actual: str) -> bool:
    left, right = _normalize(expected), _normalize(actual)
    return bool(left and right and (left in right or right in left))


def _numeric_tokens(value: object) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", str(value or "")))


def evaluate_bare_payload(case: Mapping[str, object], payload: Mapping[str, object]) -> dict[str, object]:
    expected = [item for item in case.get("requirements", ()) if isinstance(item, Mapping)]
    generated = [item for item in payload.get("requirements", ()) if isinstance(item, Mapping)]
    matched = sum(
        1 for item in generated
        if any(_matches(str(item.get("statement", "")), str(reference.get("statement", ""))) for reference in expected)
    )
    expected_numeric = set().union(*(_numeric_tokens(item.get("statement")) for item in expected)) if expected else set()
    generated_numeric = set().union(*(_numeric_tokens(item.get("statement")) for item in generated)) if generated else set()
    unsupported = generated_numeric - expected_numeric
    atomic = sum(1 for item in generated if len(str(item.get("statement", "")).split(" and ")) == 1)
    verifiable = sum(1 for item in generated if str(item.get("verification_method", "")).strip())
    evidence = sum(1 for item in generated if str(item.get("evidence", "")).strip())
    count = len(generated)
    return {
        "requirement_precision": matched / count if count else 0.0,
        "requirement_recall": matched / len(expected) if expected else 1.0,
        "requirement_atomicity": atomic / count if count else 0.0,
        "requirement_verifiability": verifiable / count if count else 0.0,
        "unsupported_numeric_claim_rate": len(unsupported) / len(generated_numeric) if generated_numeric else 0.0,
        "trace_accuracy": 0.0,
        "RFLP_coverage": 0.0,
        "evidence_faithfulness": evidence / count if count else 0.0,
        "verification_quality": verifiable / count if count else 0.0,
        "hallucinated_entity_rate": (count - matched) / count if count else 0.0,
        "generated_requirement_count": count,
        "matched_requirement_count": matched,
    }


def run_bare_baseline(cases: Iterable[Mapping[str, object]], config: Mapping[str, object]) -> dict[str, object]:
    """Run the same model on the same input, without methodology workflow/gates/repair."""

    model = OpenAICompatibleModel(dict(config))
    results: list[dict[str, object]] = []
    for case in cases:
        request = GenerationRequest(
            "bare_llm_requirement_extraction",
            "从输入文档提取可核验需求。不要推断未出现的数字；只返回符合 schema 的 JSON。",
            {"case": dict(case)},
            _BARE_SCHEMA,
            1200,
        )
        try:
            response = model.complete_json(request)
            payload = response.payload if isinstance(response.payload, Mapping) else {}
            metrics = evaluate_bare_payload(case, payload)
            results.append({"case_id": case.get("case_id", ""), "status": "completed", "metrics": metrics})
        except Exception as exc:
            results.append({"case_id": case.get("case_id", ""), "status": "failed", "metrics": {}, "error": str(exc)})
    aggregate: dict[str, object] = {}
    for key in LLM_METRICS:
        values = [float(item.get("metrics", {}).get(key, 0.0)) for item in results if isinstance(item.get("metrics"), Mapping)]
        aggregate[key] = round(sum(values) / len(values), 6) if values else 0.0
    return {
        "track": "llm",
        "baseline": "bare_llm",
        "runtime": "configured-llm",
        "methodology_workflow": False,
        "gates": False,
        "repair": False,
        "metrics": aggregate,
        "case_results": results,
    }
