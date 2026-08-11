"""Multi-lens, schema-constrained candidate expansion."""

from __future__ import annotations

import json

from rflp_lite.application.mbse_domain_packs import validate_candidate_payload
from rflp_lite.domain.canonical import canonical_json
from rflp_lite.domain.discovery import CandidateEnvelope, ProvenanceRef
from rflp_lite.domain.errors import ContractViolation
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


def build_generation_requests(seed: dict[str, object], pack: dict[str, object]) -> tuple[GenerationRequest, ...]:
    prompts = pack.get("prompt_fragments", {})
    schemas = pack.get("element_schemas", {})
    requests = []
    for lens_id, allowed_types in LENSES:
        prompt = prompts.get(lens_id, "") if isinstance(prompts, dict) else ""
        requests.append(
            GenerationRequest(
                lens_id=lens_id,
                system_prompt=(
                    "你是系统工程候选生成器。只返回 JSON；不得批准候选；"
                    "每项必须给出 element_type、payload、source_type、source_id、rationale、confidence、assumptions。"
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
                max_tokens=3000,
            )
        )
    return tuple(requests)


def expand_candidates(state: dict[str, object], pack: dict[str, object], model: GenerativeModel) -> dict[str, object]:
    discovery = state.get("discovery")
    if not isinstance(discovery, dict) or not isinstance(discovery.get("intake"), dict):
        raise ContractViolation("build the discovery seed before expansion")
    pending_sets: list[dict[str, object]] = []
    allowed_by_lens = {lens_id: frozenset(types) for lens_id, types in LENSES}
    for request in build_generation_requests(discovery["intake"], pack):
        response = model.complete_json(request)
        raw_items = response.payload.get("items")
        if not isinstance(raw_items, list):
            raise ContractViolation(f"{request.lens_id} response requires items array")
        items = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                raise ContractViolation(f"{request.lens_id} items must be objects")
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
    result = json.loads(canonical_json(state))
    result["discovery"]["candidate_sets"] = pending_sets
    result["discovery"]["revision"] = int(discovery.get("revision", 0)) + 1
    return result
