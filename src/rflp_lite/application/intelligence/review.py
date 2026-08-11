"""Revision-safe review and edit operations for discovery candidates."""

from __future__ import annotations

import json

from rflp_lite.application.mbse_domain_packs import validate_candidate_payload
from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import ContractViolation


def _candidate(result: dict[str, object], candidate_id: str) -> dict[str, object]:
    found = []
    discovery = result.get("discovery", {})
    groups = discovery.get("candidate_sets", []) if isinstance(discovery, dict) else []
    for group in groups if isinstance(groups, list) else []:
        if isinstance(group, dict) and isinstance(group.get("items"), list):
            found.extend(item for item in group["items"] if isinstance(item, dict) and item.get("id") == candidate_id)
    if len(found) != 1:
        raise ContractViolation(f"candidate must resolve to exactly one item: {candidate_id}")
    return found[0]


def _prepare(state: dict[str, object], expected_revision: int) -> tuple[dict[str, object], dict[str, object], int]:
    result = json.loads(canonical_json(state))
    discovery = result.get("discovery")
    if not isinstance(discovery, dict):
        raise ContractViolation("discovery state is required")
    current = int(discovery.get("revision", 0))
    if current != expected_revision:
        raise ContractViolation(f"stale discovery revision: expected {expected_revision}, current {current}")
    return result, discovery, current


def review_candidate(state: dict[str, object], candidate_id: str, decision: str, expected_revision: int) -> dict[str, object]:
    if decision not in {"accepted", "rejected"}:
        raise ContractViolation("decision must be accepted or rejected")
    result, discovery, old_revision = _prepare(state, expected_revision)
    item = _candidate(result, candidate_id)
    if decision == "accepted" and not item.get("provenance"):
        raise ContractViolation("accepted candidate requires provenance")
    previous = str(item.get("status", "candidate"))
    item["status"] = decision
    new_revision = old_revision + 1
    history = discovery.setdefault("review_history", [])
    event = {
        "candidate_id": candidate_id,
        "previous_status": previous,
        "decision": decision,
        "old_revision": old_revision,
        "new_revision": new_revision,
        "decision_hash": canonical_hash((candidate_id, previous, decision, old_revision, new_revision)),
        "invalidated_ids": [],
    }
    if not isinstance(history, list):
        raise ContractViolation("review_history must be a list")
    history.append(event)
    discovery["revision"] = new_revision
    return result


def edit_candidate(state: dict[str, object], candidate_id: str, payload: dict[str, object], expected_revision: int, pack: dict[str, object]) -> dict[str, object]:
    result, discovery, old_revision = _prepare(state, expected_revision)
    item = _candidate(result, candidate_id)
    element_type = str(item.get("element_type", ""))
    updated_payload = validate_candidate_payload(pack, element_type, payload)
    previous = str(item.get("status", "candidate"))
    item["payload"] = updated_payload
    item["content_hash"] = canonical_hash((element_type, updated_payload))
    item["status"] = "accepted"
    invalidated: list[str] = []
    frontier = [candidate_id]
    groups = discovery.get("candidate_sets", [])
    while frontier:
        source_id = frontier.pop(0)
        for group in groups if isinstance(groups, list) else []:
            for child in group.get("items", []) if isinstance(group, dict) and isinstance(group.get("items"), list) else []:
                if not isinstance(child, dict) or child.get("id") in invalidated or child.get("id") == candidate_id:
                    continue
                provenance = child.get("provenance", [])
                if not any(isinstance(ref, dict) and ref.get("source_id") == source_id for ref in provenance if isinstance(provenance, list)):
                    continue
                if child.get("status") in {"accepted", "candidate"}:
                    child["status"] = "stale"
                    invalidated.append(str(child.get("id", "")))
                    frontier.append(str(child.get("id", "")))
    new_revision = old_revision + 1
    history = discovery.setdefault("review_history", [])
    if not isinstance(history, list):
        raise ContractViolation("review_history must be a list")
    history.append({"candidate_id": candidate_id, "previous_status": previous, "decision": "edited", "old_revision": old_revision, "new_revision": new_revision, "invalidated_ids": sorted(invalidated), "decision_hash": canonical_hash((candidate_id, previous, "edited", old_revision, new_revision, updated_payload))})
    discovery["revision"] = new_revision
    return result
