"""Formal, deterministic acceptance checks for the generated MBSE views."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy

from rflp_lite.application.mbse_modeling import apply_mbse_edit
from rflp_lite.application.mbse_semantics import mbse_entity_index
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import ContractViolation


def _items(model: Mapping[str, object], collection: str) -> tuple[dict[str, object], ...]:
    value = model.get(collection, ())
    return tuple(item for item in value if isinstance(item, dict)) if isinstance(value, (list, tuple)) else ()


def _flow_views(model: Mapping[str, object]) -> dict[str, dict[str, tuple[str, str]]]:
    views: dict[str, dict[str, tuple[str, str]]] = {"use_cases": {}, "activities": {}, "messages": {}}
    for collection in views:
        for item in _items(model, collection):
            flow_id = str(item.get("canonical_flow_id", ""))
            flow_hash = str(item.get("canonical_flow_hash", ""))
            if flow_id and flow_hash:
                views[collection][flow_id] = (flow_id, flow_hash)
    return views


def _projection_requirements(model: Mapping[str, object]) -> set[str]:
    values: set[str] = set()
    for collection in ("use_cases", "activities", "messages"):
        for item in _items(model, collection):
            raw = item.get("requirement_ids", ())
            if isinstance(raw, (list, tuple)):
                values.update(str(value) for value in raw if str(value))
    return values


def evaluate_mbse_acceptance(state: dict[str, object]) -> dict[str, object]:
    """Return coverage, cross-view consistency, trace and edit-CAS metrics."""

    model = state.get("mbse")
    if not isinstance(model, dict):
        return {
            "requirement_coverage": 0.0,
            "cross_view_consistency": 0.0,
            "trace_complete": 0.0,
            "projection_complete": False,
            "edit_cas_verified": False,
            "edited_target_id": "",
            "unrelated_stale_count": 0,
            "diagnostics": ["MBSE semantic model not generated"],
        }

    accepted_requirements = {
        str(item.get("id", ""))
        for item in state.get("structured_requirements", ())
        if isinstance(item, dict) and str(item.get("status", "accepted")) == "accepted" and str(item.get("id", ""))
    }
    projected_requirements = _projection_requirements(model)
    covered = accepted_requirements & projected_requirements
    requirement_coverage = len(covered) / len(accepted_requirements) if accepted_requirements else 0.0

    views = _flow_views(model)
    flow_keys = set().union(*(set(value) for value in views.values()))
    consistency_count = 0
    consistency_diagnostics: list[str] = []
    for flow_id in sorted(flow_keys):
        values = [views[name].get(flow_id) for name in views]
        if all(value is not None for value in values) and len({value[1] for value in values if value is not None}) == 1:
            consistency_count += 1
        else:
            consistency_diagnostics.append(f"flow projection mismatch: {flow_id}")
    cross_view_consistency = consistency_count / len(flow_keys) if flow_keys else 0.0

    semantic = model.get("semantic_model")
    semantic_ids: set[str] = set()
    if isinstance(semantic, dict):
        try:
            semantic_ids = set(mbse_entity_index(semantic))
        except ContractViolation:
            semantic_ids = set()
    projection_ids = {
        str(item.get("id", ""))
        for collection in ("actors", "use_cases", "activities", "lifelines", "messages")
        for item in _items(model, collection)
        if str(item.get("id", ""))
    }
    trace_links = _items(model, "trace_links")
    trace_complete = bool(trace_links) and all(
        str(link.get("source_id", "")) in semantic_ids and str(link.get("target_id", "")) in semantic_ids
        for link in trace_links
    ) and all(
        any(str(link.get("source_id", "")) == requirement_id or str(link.get("target_id", "")) == requirement_id for link in trace_links)
        for requirement_id in accepted_requirements
    )
    projection_complete = bool(_items(model, "use_cases") and _items(model, "activities") and _items(model, "messages"))

    edited_target_id = ""
    edit_cas_verified = False
    unrelated_stale_count = 0
    messages = _items(model, "messages")
    if messages:
        target = messages[0]
        edited_target_id = str(target.get("id", ""))
        before_revision = str(model.get("revision", ""))
        edited = apply_mbse_edit(
            deepcopy(state),
            before_revision,
            {"kind": "update-fields", "id": edited_target_id, "fields": {"message": f"{target.get('name', '')}（验收编辑）"}},
        )
        edited_model = edited.get("mbse") if isinstance(edited, dict) else None
        if isinstance(edited_model, dict):
            stale_ids = set(str(value) for value in edited.get("stale_entities", ()))
            target_status = next((str(item.get("status")) for item in _items(edited_model, "messages") if str(item.get("id")) == edited_target_id), "")
            unrelated_stale_count = len(stale_ids - {edited_target_id})
            try:
                apply_mbse_edit(
                    edited,
                    before_revision,
                    {"kind": "update-fields", "id": edited_target_id, "fields": {"message": "过期编辑"}},
                )
            except ContractViolation:
                edit_cas_verified = str(edited_model.get("revision", "")) != before_revision and target_status == "stale"

    diagnostics = consistency_diagnostics
    if not semantic_ids:
        diagnostics = [*diagnostics, "semantic entity index unavailable"]
    return {
        "requirement_coverage": round(requirement_coverage, 4),
        "cross_view_consistency": round(cross_view_consistency, 4),
        "trace_complete": 1.0 if trace_complete else 0.0,
        "projection_complete": projection_complete,
        "edit_cas_verified": edit_cas_verified,
        "edited_target_id": edited_target_id,
        "unrelated_stale_count": unrelated_stale_count,
        "diagnostics": diagnostics,
        "metrics_hash": canonical_hash({
            "requirement_coverage": round(requirement_coverage, 4),
            "cross_view_consistency": round(cross_view_consistency, 4),
            "trace_complete": trace_complete,
            "projection_complete": projection_complete,
            "edit_cas_verified": edit_cas_verified,
        }),
    }


__all__ = ["evaluate_mbse_acceptance"]
