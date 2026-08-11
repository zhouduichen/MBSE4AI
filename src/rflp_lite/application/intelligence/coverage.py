"""Bounded coverage audit for stakeholder, lifecycle and scenario dimensions."""

from __future__ import annotations

import json

from rflp_lite.application.mbse_domain_packs import validate_candidate_payload
from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.discovery import CandidateEnvelope, ProvenanceRef
from rflp_lite.domain.errors import AdapterFailure, ContractViolation
from rflp_lite.ports.generative_model import GenerationRequest, GenerativeModel


def coverage_status(matches: list[dict[str, object]]) -> str:
    if any(item.get("status") == "accepted" for item in matches):
        return "covered"
    if matches:
        return "candidate"
    return "unknown"


def _items(state: dict[str, object]) -> list[dict[str, object]]:
    discovery = state.get("discovery", {})
    groups = discovery.get("candidate_sets", []) if isinstance(discovery, dict) else []
    values: list[dict[str, object]] = []
    for group in groups if isinstance(groups, list) else []:
        if isinstance(group, dict) and isinstance(group.get("items"), list):
            values.extend(item for item in group["items"] if isinstance(item, dict))
    return values


def _cells(state: dict[str, object], pack: dict[str, object]) -> list[dict[str, object]]:
    items = _items(state)
    cells: list[dict[str, object]] = []
    rules = pack.get("coverage_rules", [])
    for rule in rules if isinstance(rules, list) else []:
        if not isinstance(rule, dict):
            continue
        source = str(rule.get("source", ""))
        rule_id = str(rule.get("id", source))
        priority = str(rule.get("priority", "medium"))
        if source == "stakeholder_lenses":
            for lens in pack.get("stakeholder_lenses", []) if isinstance(pack.get("stakeholder_lenses"), list) else []:
                if not isinstance(lens, dict):
                    continue
                lens_id = str(lens.get("id", ""))
                matches = [item for item in items if item.get("element_type") == "stakeholder" and isinstance(item.get("payload"), dict) and str(item["payload"].get("category", "")) == lens_id]
                cells.append({"rule_id": rule_id, "priority": priority, "key": f"stakeholder-lenses/{lens_id}", "status": coverage_status(matches), "matched_ids": [str(item.get("id", "")) for item in matches]})
        elif source == "lifecycle_phases":
            for phase in pack.get("lifecycle_phases", []) if isinstance(pack.get("lifecycle_phases"), list) else []:
                if not isinstance(phase, dict):
                    continue
                phase_id = str(phase.get("id", ""))
                matches = [item for item in items if item.get("element_type") == "lifecycle_phase" and isinstance(item.get("payload"), dict) and str(item["payload"].get("phase_id", "")) == phase_id]
                cells.append({"rule_id": rule_id, "priority": priority, "key": f"lifecycle-phases/{phase_id}", "status": coverage_status(matches), "matched_ids": [str(item.get("id", "")) for item in matches]})
        elif source == "scenario_dimensions":
            dimensions = pack.get("scenario_dimensions", [])
            for dimension in dimensions if isinstance(dimensions, list) else []:
                if not isinstance(dimension, dict):
                    continue
                dimension_id = str(dimension.get("id", ""))
                values = dimension.get("values", [])
                for value in values if isinstance(values, list) else []:
                    value_text = str(value)
                    matches = []
                    for item in items:
                        payload = item.get("payload")
                        if item.get("element_type") not in {"operational_scenario", "scenario"} or not isinstance(payload, dict):
                            continue
                        contexts = payload.get("contexts") or payload.get("dimensions") or {}
                        if isinstance(contexts, dict) and str(contexts.get(dimension_id, "")) == value_text:
                            matches.append(item)
                    cells.append({"rule_id": rule_id, "priority": priority, "key": f"scenario-dimensions/{dimension_id}/{value_text}", "status": coverage_status(matches), "matched_ids": [str(item.get("id", "")) for item in matches]})
    coverage = state.get("discovery", {}).get("coverage", {}) if isinstance(state.get("discovery"), dict) else {}
    waivers = coverage.get("waivers", {}) if isinstance(coverage, dict) else {}
    for cell in cells:
        if isinstance(waivers, dict) and cell["key"] in waivers:
            cell["status"] = "not_applicable"
    return sorted(cells, key=lambda cell: (cell["rule_id"], cell["key"]))


def evaluate_coverage(state: dict[str, object], pack: dict[str, object]) -> dict[str, object]:
    result = json.loads(canonical_json(state))
    discovery = result.setdefault("discovery", {})
    cells = _cells(result, pack)
    summary = {status: sum(1 for cell in cells if cell["status"] == status) for status in ("covered", "candidate", "unknown", "not_applicable")}
    discovery["coverage"] = {**(discovery.get("coverage", {}) if isinstance(discovery.get("coverage"), dict) else {}), "cells": cells, "summary": summary}
    discovery["revision"] = int(discovery.get("revision", 0)) + 1
    return result


def fill_high_priority_gaps(state: dict[str, object], pack: dict[str, object], model: GenerativeModel) -> dict[str, object]:
    existing = state.get("discovery", {}).get("coverage", {}) if isinstance(state.get("discovery"), dict) else {}
    if isinstance(existing, dict) and existing.get("gap_fill_attempted"):
        return json.loads(canonical_json(state))
    evaluated = evaluate_coverage(state, pack)
    coverage = evaluated["discovery"]["coverage"]
    cells = [cell for cell in coverage["cells"] if cell["status"] == "unknown" and cell["priority"] == "high"]
    request = GenerationRequest(
        lens_id="coverage_gap_fill",
        system_prompt="只返回用于补齐高优先级覆盖缺口的 JSON items，不得批准候选。",
        user_payload={"seed": evaluated["discovery"].get("intake", {}), "gaps": cells},
        response_schema={"type": "object", "required": ["items"]},
        max_tokens=2000,
    )
    result = evaluated
    try:
        response = model.complete_json(request)
        raw_items = response.payload.get("items", [])
        if not isinstance(raw_items, list):
            raise ContractViolation("coverage gap fill items must be a list")
        new_items = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            element_type = str(raw.get("element_type", "operational_scenario"))
            payload = validate_candidate_payload(pack, element_type, raw.get("payload", raw))
            new_items.append(CandidateEnvelope.create(element_type=element_type, pack_id=str(pack["id"]), payload=payload, provenance=(ProvenanceRef("inferred", "coverage-gap-fill", "high priority coverage gap"),), producer="llm", confidence=float(raw.get("confidence", 0.5))).as_dict())
        if new_items:
            result["discovery"].setdefault("candidate_sets", []).append({"lens_id": "coverage_gap_fill", "input_hash": response.input_hash, "output_hash": response.output_hash, "items": new_items})
    except AdapterFailure as exc:
        result["discovery"].setdefault("diagnostics", []).append({"code": "coverage_gap_fill_failed", "message": str(exc)})
    result["discovery"]["coverage"]["gap_fill_attempted"] = True
    return evaluate_coverage(result, pack)


build_coverage_matrix = evaluate_coverage
targeted_gap_fill = fill_high_priority_gaps
