"""Multi-lens, schema-constrained candidate expansion."""

from __future__ import annotations

import json

from rflp_lite.application.mbse_domain_packs import validate_candidate_payload
from rflp_lite.domain.canonical import canonical_json
from rflp_lite.domain.discovery import CandidateEnvelope, ProvenanceRef
from rflp_lite.domain.errors import AdapterFailure, ContractViolation
from rflp_lite.ports.generative_model import GenerationRequest, GenerativeModel


LENSES = (
    ("stakeholders", ("stakeholder", "concern", "need")),
    ("environment", ("exchange_flow", "system_boundary")),
    ("lifecycle_use_cases", ("lifecycle_phase", "transition", "use_case")),
    ("scenarios", ("operational_scenario",)),
    ("capabilities_requirements", ("capability", "requirement")),
    ("functions", ("function", "functional_flow", "functional_scenario")),
    ("components_solutions", ("logical_component", "physical_block", "interface", "solution_candidate")),
    ("risks_questions", ("risk", "clarification_question")),
)


def build_generation_requests(
    seed: dict[str, object], pack: dict[str, object], lens_ids: tuple[str, ...] | None = None
) -> tuple[GenerationRequest, ...]:
    prompts = pack.get("prompt_fragments", {})
    schemas = pack.get("element_schemas", {})
    requests = []
    selected = set(lens_ids) if lens_ids is not None else None
    for lens_id, allowed_types in LENSES:
        if selected is not None and lens_id not in selected:
            continue
        prompt = prompts.get(lens_id, "") if isinstance(prompts, dict) else ""
        requests.append(
            GenerationRequest(
                lens_id=lens_id,
                system_prompt=(
                    "你是系统工程候选生成器。只返回 JSON；不得批准候选；"
                    "每项必须给出 element_type、payload、source_type、source_id、rationale、confidence、assumptions；"
                    "每个分析视角最多返回 6 项，字段保持简洁，不要输出解释文字。"
                    + str(prompt)
                ),
                user_payload={"seed": seed, "allowed_element_types": list(allowed_types)},
                response_schema={
                    "type": "object",
                    "required": ["items"],
                    "properties": {
                        "items": {"type": "array"},
                        "element_schemas": {
                            key: schemas[key] for key in allowed_types if isinstance(schemas, dict) and key in schemas
                        },
                    },
                },
                max_tokens=2400,
            )
        )
    return tuple(requests)


def _response_items(payload: dict[str, object], allowed_types: tuple[str, ...]) -> list[dict[str, object]]:
    """Accept the canonical ``items`` shape and common grouped JSON variants."""

    direct = payload.get("items")
    if isinstance(direct, list):
        return [item for item in direct if isinstance(item, dict)]

    collected: list[dict[str, object]] = []
    seen: set[str] = set()
    containers = [payload.get("element_schemas"), payload]
    for container in containers:
        if not isinstance(container, dict):
            continue
        for element_type in allowed_types:
            aliases = (element_type, f"{element_type}s")
            values = next((container.get(alias) for alias in aliases if isinstance(container.get(alias), list)), None)
            if not isinstance(values, list):
                continue
            for value in values:
                if not isinstance(value, dict):
                    continue
                marker = json.dumps(value, ensure_ascii=False, sort_keys=True)
                if marker in seen:
                    continue
                seen.add(marker)
                item = dict(value)
                item.setdefault("element_type", element_type)
                if not isinstance(item.get("payload"), dict):
                    metadata = {"element_type", "source_type", "source_id", "rationale", "confidence", "assumptions"}
                    item["payload"] = {key: value for key, value in item.items() if key not in metadata}
                collected.append(item)
    return collected


def expand_candidates(
    state: dict[str, object],
    pack: dict[str, object],
    model: GenerativeModel,
    lens_ids: tuple[str, ...] | None = None,
) -> dict[str, object]:
    result = json.loads(canonical_json(state))
    discovery = result.get("discovery")
    if not isinstance(discovery, dict) or not isinstance(discovery.get("intake"), dict):
        raise ContractViolation("build the discovery seed before expansion")
    pending_sets: list[dict[str, object]] = []
    diagnostics = discovery.setdefault("diagnostics", [])
    if not isinstance(diagnostics, list):
        diagnostics = []
        discovery["diagnostics"] = diagnostics
    allowed_by_lens = {lens_id: frozenset(types) for lens_id, types in LENSES}
    for request in build_generation_requests(discovery["intake"], pack, lens_ids):
        try:
            response = model.complete_json(request)
            raw_items = _response_items(response.payload, tuple(allowed_by_lens[request.lens_id]))
            if not raw_items:
                raise ContractViolation(f"{request.lens_id} response requires items array")
            items = []
            for raw in raw_items:
                element_type = str(raw.get("element_type", ""))
                if element_type not in allowed_by_lens[request.lens_id]:
                    raise ContractViolation(f"{request.lens_id} returned unsupported {element_type}")
                payload = validate_candidate_payload(pack, element_type, raw.get("payload"))
                source_type = str(raw.get("source_type", "inferred"))
                if source_type not in {"explicit", "derived", "inferred", "assumed", "external_reference"}:
                    source_type = "inferred"
                item = CandidateEnvelope.create(
                    element_type=element_type,
                    pack_id=str(pack["id"]),
                    payload=payload,
                    provenance=(ProvenanceRef(source_type, str(raw.get("source_id", f"lens-{request.lens_id}")), str(raw.get("rationale", ""))),),
                    producer="llm",
                    assumptions=tuple(str(value) for value in raw.get("assumptions", ())),
                    confidence=float(raw.get("confidence", 0.5)),
                )
                items.append(item.as_dict())
            pending_sets.append(
                {
                    "lens_id": request.lens_id,
                    "input_hash": response.input_hash,
                    "output_hash": response.output_hash,
                    "repaired": response.repaired,
                    "provider_id": response.provider_id,
                    "model_id": response.model_id,
                    "template_version": response.template_version,
                    "duration_ms": response.duration_ms,
                    "status": response.status,
                    "items": sorted(items, key=lambda item: str(item["id"])),
                }
            )
        except AdapterFailure as exc:
            diagnostics.append({"code": "generative_model_failed", "lens_id": request.lens_id, "severity": "warning", "message": str(exc)})
            break
        except (ContractViolation, TypeError, ValueError) as exc:
            diagnostics.append({"code": "generative_model_invalid_output", "lens_id": request.lens_id, "severity": "warning", "message": str(exc)})
            pending_sets.append({"lens_id": request.lens_id, "status": "failed", "items": [], "error": str(exc)})
    result["discovery"]["candidate_sets"] = pending_sets
    result["discovery"]["revision"] = int(discovery.get("revision", 0)) + 1
    return result
